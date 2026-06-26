"""Generate synthetic monthly committed-jobs data for the FleetSync ``jobs``
table and (optionally) load it into BigQuery.

Data model
----------
Each row in ``jobs`` represents a single committed job.  The monthly capacity
for a contractor is ``num_technicians × JOBS_PER_TECH_PER_MONTH``.  The ratio
of committed jobs to monthly capacity is what drives the capacity verdict the
Cadence agent uses when deciding whether to approve a Google Ads budget bump.

Generation window
-----------------
Historical : HISTORY_MONTHS (24) calendar months ending with the current month.
Forecast   : FORECAST_MONTHS (3) calendar months starting next month.

These jobs carry ``record_type = 'historical'`` or ``'forecast'`` respectively.
The distinction lets the view separate "what happened" from "what is pre-booked".

Idempotency
-----------
Before generating anything the script queries BigQuery for every
(contractor_id, year_month) pair that already has at least one row.  Only
pairs that are absent from that set are generated and loaded.  Re-running the
script after new months become available fills only the gaps — no duplicate
rows are ever created.

To regenerate everything from scratch, truncate the jobs table in BigQuery
first, then run with ``--load-bq``.

Usage
-----
    # Dry-run: print what would be generated; no files written, no BQ access
    python -m data_generation.generate_jobs_data --dry-run

    # Write missing months as CSV (no BQ needed)
    python -m data_generation.generate_jobs_data

    # Write missing months and load them straight into BigQuery
    python -m data_generation.generate_jobs_data --load-bq
"""

from __future__ import annotations

import argparse
import csv
import os
import random
from datetime import date
from pathlib import Path
from typing import Any

from config.contractors import CONTRACTORS, Contractor

# ── Generation constants (code-only; NOT in .env) ──────────────────────────────
# The number of jobs a single technician can complete in one calendar month.
# Monthly capacity for a contractor = num_technicians × JOBS_PER_TECH_PER_MONTH.
JOBS_PER_TECH_PER_MONTH: int = 10

# How many complete calendar months of historical data to maintain.
# The generator will ensure rows exist for every month in this window.
HISTORY_MONTHS: int = 24

# How many months ahead to pre-populate with forecast (pre-committed) jobs.
# These represent work already scheduled but not yet delivered.
FORECAST_MONTHS: int = 3

# Fraction of monthly capacity that is already pre-booked in forecast months.
# e.g. 0.70 → 70 % of a contractor's monthly slots are committed in advance;
# the remaining 30 % are still open for new leads driven by Google Ads.
FUTURE_BOOKING_RATE: float = 0.70

# Monthly demand multipliers by trade (index 0 = January, 11 = December).
# Values > 1.0 mean above-average demand; < 1.0 means a quieter month.
# Multiplied against sim_base_util to determine how many jobs to commit.
MONTHLY_FACTORS: dict[str, list[float]] = {
    #                Jan   Feb   Mar   Apr   May   Jun   Jul   Aug   Sep   Oct   Nov   Dec
    "HVAC":        [0.70, 0.72, 0.80, 0.88, 1.00, 1.20, 1.30, 1.25, 1.00, 0.82, 0.88, 0.95],
    "Plumbing":    [1.10, 1.00, 0.92, 0.88, 0.88, 0.85, 0.82, 0.82, 0.88, 0.92, 1.00, 1.10],
    "Electrical":  [0.90, 0.90, 0.92, 0.95, 1.00, 1.05, 1.10, 1.08, 1.00, 0.95, 0.95, 0.92],
    "Roofing":     [0.65, 0.70, 0.88, 1.10, 1.20, 1.15, 1.05, 1.00, 1.10, 1.20, 0.88, 0.65],
}

# Specific job types offered by each trade.
# Each generated job randomly picks one of these.
JOB_TYPES: dict[str, list[str]] = {
    "HVAC": [
        "AC Tune-Up", "AC Repair", "Furnace Installation",
        "Heat Pump Service", "Duct Cleaning", "Thermostat Installation",
        "Air Handler Replacement", "Refrigerant Recharge",
        "Blower Motor Repair", "Compressor Replacement",
    ],
    "Plumbing": [
        "Pipe Repair", "Water Heater Installation", "Drain Cleaning",
        "Faucet Replacement", "Toilet Repair", "Sewer Line Inspection",
        "Water Softener Install", "Garbage Disposal Replacement",
        "Backflow Prevention", "Re-Pipe Service",
    ],
    "Electrical": [
        "Panel Upgrade", "Outlet Installation", "Circuit Breaker Replacement",
        "EV Charger Installation", "Lighting Installation", "Safety Inspection",
        "Ceiling Fan Install", "Smoke Detector Wiring",
        "Generator Hook-Up", "Surge Protector Install",
    ],
    "Roofing": [
        "Roof Replacement", "Storm Damage Repair", "Gutter Installation",
        "Roof Inspection", "Shingle Replacement", "Flat Roof Repair",
        "Skylight Installation", "Fascia Repair",
        "Chimney Flashing", "Roof Ventilation Install",
    ],
}

# Estimated job value range (min USD, max USD) by trade.
# Values are drawn uniformly within these bounds to simulate real invoice spread.
JOB_VALUE_RANGES: dict[str, tuple[float, float]] = {
    "HVAC":        (150.0,  1_200.0),
    "Plumbing":    (100.0,    800.0),
    "Electrical":  (150.0,  2_000.0),
    "Roofing":     (500.0, 15_000.0),
}

# ── Synthetic client data pools ─────────────────────────────────────────────────
# All values are entirely fictitious.  No real personal data is used.
# Combined randomly to produce plausible-looking (but fake) client records.

CLIENT_FIRST_NAMES: list[str] = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer",
    "Michael", "Linda", "William", "Barbara", "David", "Susan",
    "Richard", "Jessica", "Joseph", "Sarah", "Thomas", "Karen",
    "Charles", "Lisa", "Daniel", "Betty", "Mark", "Dorothy", "Paul",
]
CLIENT_LAST_NAMES: list[str] = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Martinez", "Wilson", "Anderson", "Taylor",
    "Thomas", "Hernandez", "Moore", "Martin", "Jackson", "Thompson",
    "White", "Lopez", "Harris", "Clark", "Lewis", "Robinson", "Walker",
]

# Generic US street names and suffix types used to build fake addresses.
STREET_NAMES: list[str] = [
    "Oak", "Maple", "Pine", "Cedar", "Elm", "Washington", "Lincoln",
    "Jefferson", "Highland", "Valley", "Sunset", "Riverside",
    "Willow", "Park", "Lake", "Forest", "Church", "Spring",
]
STREET_SUFFIXES: list[str] = ["St", "Ave", "Blvd", "Dr", "Ln", "Rd", "Ct", "Way", "Pl"]

# ── Job status weights by time relative to today ────────────────────────────────
# These weights ensure the data looks realistic: past jobs are mostly completed,
# current-month jobs are still in flight, and future jobs are scheduled only.

# Historical months (before current month): most work is done.
_PAST_STATUS: list[tuple[str, float]] = [
    ("completed",   0.82),
    ("cancelled",   0.10),
    ("in_progress", 0.08),  # small residual — paperwork not yet closed
]

# Current month: active work mix.
_CURRENT_STATUS: list[tuple[str, float]] = [
    ("scheduled",   0.45),
    ("in_progress", 0.40),
    ("completed",   0.15),
]

# Future months: nothing has started yet.
_FUTURE_STATUS: list[tuple[str, float]] = [
    ("scheduled", 1.0),
]


# ── Month arithmetic helpers (pure stdlib — no dateutil dependency) ──────────────

def _first_of_month(year: int, month: int) -> date:
    """Return DATE(year, month, 1) — the anchor used for BQ partitioning."""
    return date(year, month, 1)


def _add_months(d: date, months: int) -> date:
    """Shift a date forward or backward by `months` calendar months.

    Always lands on the 1st of the resulting month so arithmetic stays clean.
    Works purely with stdlib — no external packages needed.
    """
    # Express the date as a total 0-based month count from the year-0 origin,
    # add the offset, then convert back to (year, month).
    total = d.year * 12 + (d.month - 1) + months
    year, month_idx = divmod(total, 12)   # month_idx is 0-based (Jan = 0)
    return date(year, month_idx + 1, 1)   # back to 1-based month


def _to_year_month(d: date) -> str:
    """Format a date as 'YYYY-MM' — the format stored in the year_month column."""
    return d.strftime("%Y-%m")


# ── BigQuery helpers ─────────────────────────────────────────────────────────────

def _bq_client(project: str, location: str):
    """Create and return a BigQuery client.  Imported lazily so the module can
    be imported without the google-cloud-bigquery package installed (e.g. in
    dry-run mode or unit tests that don't need BQ access).
    """
    from google.cloud import bigquery
    return bigquery.Client(project=project, location=location)


def get_existing_months(project: str, dataset: str, location: str) -> set[tuple[str, str]]:
    """Query BigQuery for every (contractor_id, year_month) pair that already
    has at least one row in the jobs table.

    This is the idempotency check: pairs present here are skipped by the
    generator so we never insert duplicates.

    Returns an empty set if the table does not exist yet (first-run scenario).
    """
    from google.cloud import bigquery

    client = _bq_client(project, location)

    try:
        # DISTINCT means we only care whether *any* row exists for the pair,
        # not how many.  This is fast even on a large table.
        query = f"""
            SELECT DISTINCT contractor_id, year_month
            FROM `{project}.{dataset}.jobs`
        """
        result = client.query(query).result()
        return {(row["contractor_id"], row["year_month"]) for row in result}

    except Exception as exc:
        # Most likely reason: table doesn't exist yet.  Treat as empty so the
        # generator proceeds to create all months from scratch.
        print(f"[INFO] Could not query existing jobs (first run?): {exc}")
        return set()


def load_into_bigquery(csv_path: Path, project: str, dataset: str, location: str) -> int:
    """Append rows from a CSV file into the BigQuery jobs table.

    Uses WRITE_APPEND so existing rows are never touched — only the newly
    generated rows are added.  Returns the total row count in the table after
    the load completes.
    """
    from google.cloud import bigquery

    client = _bq_client(project, location)
    table_id = f"{project}.{dataset}.jobs"

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,    # row 0 is the CSV header
        autodetect=True,        # let BQ infer column types from data
        # WRITE_APPEND: add rows to the existing table; never overwrite.
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )

    with csv_path.open("rb") as fh:
        load_job = client.load_table_from_file(fh, table_id, job_config=job_config)

    load_job.result()  # block until the load job finishes (raises on error)

    table = client.get_table(table_id)
    return table.num_rows   # total rows now in the table


# ── Row generation ───────────────────────────────────────────────────────────────

def _job_status(year_month: str, rng: random.Random) -> str:
    """Return a realistic job status for the given month.

    Past months are mostly completed; the current month is still in-flight;
    future months are all pre-scheduled.
    """
    today_ym = _to_year_month(date.today())  # e.g. '2026-06'

    if year_month < today_ym:
        # Month has already passed — most jobs are done.
        choices, weights = zip(*_PAST_STATUS)
    elif year_month == today_ym:
        # Current month — active work is ongoing.
        choices, weights = zip(*_CURRENT_STATUS)
    else:
        # Future month — nothing has started yet.
        choices, weights = zip(*_FUTURE_STATUS)

    return rng.choices(list(choices), weights=list(weights))[0]


def _fake_client(rng: random.Random, contractor: Contractor) -> dict[str, str]:
    """Generate a fictitious client record anchored to the contractor's city.

    All data is synthetic.  The phone format (555-NXX-XXXX) follows NANP
    conventions for obviously fictional numbers.
    """
    first = rng.choice(CLIENT_FIRST_NAMES)
    last  = rng.choice(CLIENT_LAST_NAMES)

    # House number + street name + suffix gives a plausible address.
    house   = rng.randint(100, 9999)
    street  = rng.choice(STREET_NAMES)
    suffix  = rng.choice(STREET_SUFFIXES)
    address = f"{house} {street} {suffix}"

    # 555-NXX-XXXX: exchange 200-999, subscriber 1000-9999.
    exchange = rng.randint(200, 999)
    number   = rng.randint(1000, 9999)
    phone    = f"(555) {exchange}-{number}"

    return {
        "client_name":    f"{first} {last}",
        "client_address": address,
        "client_city":    contractor.city,    # same metro as the contractor
        "client_state":   contractor.state,
        "client_phone":   phone,
    }


def _jobs_for_month(
    contractor: Contractor,
    year_month: str,
    record_type: str,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Generate all job rows for a single (contractor, month) pair.

    The number of jobs committed is calculated as:
        monthly_capacity = num_technicians × JOBS_PER_TECH_PER_MONTH
        seasonal_factor  = MONTHLY_FACTORS[trade][month - 1]
        effective_util   = sim_base_util × seasonal_factor
                           × FUTURE_BOOKING_RATE   (forecast months only)
        committed_count  = round(monthly_capacity × min(effective_util, 1.05))

    Capping at 1.05 allows a slight over-commitment (realistic) while preventing
    absurdly high numbers.  A minimum of 1 job is always generated so every
    (contractor, month) pair has at least one row.

    Args:
        contractor  : Contractor config object (num_technicians, sim_base_util, …).
        year_month  : Target month as 'YYYY-MM' string.
        record_type : 'historical' or 'forecast'.
        rng         : Seeded random instance (deterministic per pair).

    Returns:
        List of row dicts, each mapping directly to a column in the jobs table.
    """
    year_int  = int(year_month[:4])
    month_int = int(year_month[5:7])

    # First day of the month — stored as a DATE in BQ for partition pruning.
    job_month_date = _first_of_month(year_int, month_int)

    # How many jobs can this contractor's entire fleet handle in a month?
    monthly_capacity = contractor.num_technicians * JOBS_PER_TECH_PER_MONTH

    # Seasonal factor adjusts demand up or down depending on the time of year.
    # Index is 0-based: January = index 0, December = index 11.
    seasonal_factor = MONTHLY_FACTORS[contractor.trade][month_int - 1]

    # Effective utilisation = contractor's normal level × seasonal adjustment.
    # sim_base_util is a generator-only seed stored in config/contractors.py.
    effective_util = contractor.sim_base_util * seasonal_factor

    if record_type == "forecast":
        # Future months: only a fraction of capacity is pre-booked.
        # The rest is still open — exactly what Google Ads leads would fill.
        effective_util *= FUTURE_BOOKING_RATE

    # Cap at 1.05 to model slight over-commitment; floor at 0 for safety.
    committed_count = max(round(monthly_capacity * min(effective_util, 1.05)), 1)

    rows: list[dict[str, Any]] = []

    for i in range(committed_count):
        # Unique job ID: contractor + month + zero-padded sequence index.
        job_id = f"{contractor.contractor_id}-{year_month}-{i:04d}"

        job_type = rng.choice(JOB_TYPES[contractor.trade])  # pick a specific job type
        client   = _fake_client(rng, contractor)             # generate fake client info

        # Draw a job value uniformly from the trade's typical invoice range.
        lo, hi = JOB_VALUE_RANGES[contractor.trade]
        estimated_value = round(rng.uniform(lo, hi), 2)

        status = _job_status(year_month, rng)  # realistic status for this month

        rows.append({
            "job_id":              job_id,
            "contractor_id":       contractor.contractor_id,
            "year_month":          year_month,                  # 'YYYY-MM' for GROUP BY
            "job_month":           job_month_date.isoformat(),  # DATE '2026-06-01' for partitioning
            "trade":               contractor.trade,
            "job_type":            job_type,
            "client_name":         client["client_name"],
            "client_address":      client["client_address"],
            "client_city":         client["client_city"],
            "client_state":        client["client_state"],
            "client_phone":        client["client_phone"],
            "status":              status,
            "estimated_value_usd": estimated_value,
            "record_type":         record_type,  # 'historical' | 'forecast'
        })

    return rows


def _target_months() -> list[tuple[str, str]]:
    """Return every (year_month, record_type) pair in the generation window.

    The window is:
        HISTORY_MONTHS months ending with the current month → 'historical'
        FORECAST_MONTHS months starting next month          → 'forecast'
    """
    today = date.today()
    # Snap to the first day of the current month so _add_months arithmetic is
    # always anchored at a month boundary.
    current = _first_of_month(today.year, today.month)

    result: list[tuple[str, str]] = []

    # Historical window: HISTORY_MONTHS back through and including this month.
    for offset in range(-HISTORY_MONTHS, 1):  # -24, -23, …, 0
        result.append((_to_year_month(_add_months(current, offset)), "historical"))

    # Forecast window: next FORECAST_MONTHS months.
    for offset in range(1, FORECAST_MONTHS + 1):  # 1, 2, 3
        result.append((_to_year_month(_add_months(current, offset)), "forecast"))

    return result


def generate_missing(
    existing: set[tuple[str, str]],
    seed: int = 42,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Generate job rows for every (contractor, month) pair absent from `existing`.

    Uses a per-pair seed derived from the global seed so each (contractor, month)
    always produces the same rows regardless of which other months are generated
    in the same run.  This makes reruns fully deterministic.

    Args:
        existing : Set of (contractor_id, year_month) already present in BQ.
        seed     : Base random seed for reproducibility.

    Returns:
        A tuple of:
            rows    — flat list of job-row dicts ready to write to CSV / BQ.
            pairs   — list of (contractor_id, year_month) that were generated.
    """
    all_rows: list[dict[str, Any]] = []
    generated_pairs: list[tuple[str, str]] = []

    for year_month, record_type in _target_months():
        for contractor in CONTRACTORS:
            key = (contractor.contractor_id, year_month)

            if key in existing:
                # Already in BigQuery — skip to avoid duplicate rows.
                continue

            # Derive a deterministic per-pair seed so re-running the script
            # for any subset of months always produces the same job rows.
            # We combine the global seed with a numeric fingerprint of the pair.
            pair_fingerprint = sum(ord(c) for c in contractor.contractor_id) * 10_000
            pair_fingerprint += int(year_month.replace("-", ""))
            pair_rng = random.Random(seed + pair_fingerprint)

            rows = _jobs_for_month(contractor, year_month, record_type, pair_rng)
            all_rows.extend(rows)
            generated_pairs.append(key)

    return all_rows, generated_pairs


def _write_csv(rows: list[dict[str, Any]], out_path: Path) -> None:
    """Write row dicts to a CSV file with a header row derived from dict keys."""
    if not rows:
        return  # nothing to write — caller prints a message

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Extract column order from the first row (all rows share the same keys).
    fieldnames = list(rows[0].keys())

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotent monthly job generator.  Fills only the months that are "
            "missing from BigQuery; never overwrites existing rows."
        )
    )
    parser.add_argument(
        "--load-bq", action="store_true",
        help="Load the generated CSV into BigQuery after writing it locally.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print a summary of what would be generated; write no files and "
             "skip all BigQuery access.",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Base random seed for reproducible generation (default: 42).  "
             "Changing this produces different client names / values.",
    )
    parser.add_argument(
        "--out-dir", default="data_out",
        help="Local directory for the output CSV (default: data_out/).",
    )
    args = parser.parse_args()

    # ── Step 1: Determine which (contractor, month) pairs already exist in BQ ──

    if args.dry_run:
        # Dry-run bypasses all BQ and filesystem access — just show the plan.
        existing: set[tuple[str, str]] = set()
        print("[DRY-RUN] Treating all months as missing (no BQ query).")
    elif args.load_bq:
        # Real run: query BQ so we only generate what's missing.
        project  = os.environ.get("GOOGLE_CLOUD_PROJECT")
        dataset  = os.environ.get("BQ_DATASET", "fleetsync")
        location = os.environ.get("BQ_LOCATION", "US")
        if not project:
            raise SystemExit(
                "GOOGLE_CLOUD_PROJECT env var is required for --load-bq.  "
                "See .env.example."
            )
        print("[INFO] Checking BigQuery for already-loaded months …")
        existing = get_existing_months(project, dataset, location)
        print(f"[INFO] Found {len(existing)} existing (contractor, month) pairs in BQ.")
    else:
        # Local-only run (write CSV but skip BQ): generate everything.
        existing = set()

    # ── Step 2: Generate rows for every missing (contractor, month) pair ────────

    rows, generated_pairs = generate_missing(existing, seed=args.seed)

    # Summarise the generation plan for the user.
    total_pairs = len(CONTRACTORS) * (HISTORY_MONTHS + 1 + FORECAST_MONTHS)
    print(
        f"[INFO] Window: {HISTORY_MONTHS} historical + {FORECAST_MONTHS} forecast months "
        f"× {len(CONTRACTORS)} contractors = {total_pairs} total pairs."
    )
    print(
        f"[INFO] Already present: {len(existing)}"
        f"  |  To generate: {len(generated_pairs)}"
        f"  |  Total rows: {len(rows)}"
    )

    if args.dry_run:
        # Print at most 20 sample pairs so the output is readable.
        for cid, ym in sorted(generated_pairs)[:20]:
            monthly_cap = next(
                c.num_technicians * JOBS_PER_TECH_PER_MONTH
                for c in CONTRACTORS if c.contractor_id == cid
            )
            print(f"  Would generate: {cid:5s}  {ym}  (capacity {monthly_cap} jobs/month)")
        if len(generated_pairs) > 20:
            print(f"  … and {len(generated_pairs) - 20} more pairs")
        return

    if not rows:
        # Nothing to do — all months are already in BigQuery.
        print("[INFO] Nothing to do — all months already present in BigQuery.")
        return

    # ── Step 3: Write generated rows to a local CSV ─────────────────────────────

    out_path = Path(args.out_dir) / "fleetsync_jobs.csv"
    _write_csv(rows, out_path)
    print(f"[INFO] Wrote {len(rows)} rows ({len(generated_pairs)} contractor-month pairs) → {out_path}")

    # ── Step 4: Append to BigQuery (only when --load-bq was passed) ─────────────

    if args.load_bq:
        project  = os.environ.get("GOOGLE_CLOUD_PROJECT")
        dataset  = os.environ.get("BQ_DATASET", "fleetsync")
        location = os.environ.get("BQ_LOCATION", "US")
        print(f"[INFO] Appending to {project}.{dataset}.jobs …")
        total_after = load_into_bigquery(out_path, project, dataset, location)
        print(f"[INFO] Done.  Table now contains {total_after:,} total rows.")


if __name__ == "__main__":
    main()
