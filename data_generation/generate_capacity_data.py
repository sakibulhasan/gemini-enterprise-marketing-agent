"""Generate synthetic FleetSync capacity / dispatch data and load it into BigQuery.

FleetSync is the (synthetic) dispatch system. It is the *key differentiator* in
the use case: it answers "can this contractor even handle more leads right now?".
We model three tables:

* ``contractors``         - one row per contractor (static profile).
* ``technician_capacity`` - one row per contractor per day (the capacity signal).
* ``dispatch_jobs``       - one row per scheduled/completed job (operational detail).

This is the BigQuery connector half of the demo (Google Ads recommendations are
read with a separate Cloud Storage connector; weather with a REST connector).

The capacity numbers are correlated with the contractor's technician count, and
roofers/plumbers get a demand spike injected on stormy days so the weather
signal in the agent has something to interact with.

Usage
-----
    # write CSVs locally only (no GCP needed)
    python -m data_generation.generate_capacity_data --days 30 --local-only

    # generate AND load into BigQuery (reads GOOGLE_CLOUD_PROJECT / BQ_DATASET from env)
    python -m data_generation.generate_capacity_data --days 30 --load-bq
"""

from __future__ import annotations

import argparse
import csv
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from config.contractors import CONTRACTORS, Contractor

# ---- Generation constants (code-only — not in .env) ----
# How many jobs one technician can handle per day.
JOBS_PER_TECH_PER_DAY: float = 3.0
# Probability (0–1) that a weather event fires for Roofing/Plumbing on a given day.
STORM_PROBABILITY: float = 0.12
# Demand multiplier applied when a weather event fires (e.g. 0.80 × 1.5 = 1.20).
STORM_DEMAND_MULTIPLIER: float = 1.5
# Weekends are busier — customers are home, more likely to call.
WEEKEND_BOOST: float = 1.15
# Days of historical capacity rows to generate (2 calendar years).
HISTORY_DAYS: int = 730
# Days ahead to generate pre-committed (forecast) job rows.
FUTURE_DAYS: int = 60
# Fraction of normal capacity already pre-committed for future dates.
# E.g. a contractor with sim_base_util=0.80 has 0.80 × 0.75 = 0.60 of capacity
# pre-booked for next week — leaving 0.40 still open for new leads.
FUTURE_BOOKING_RATE: float = 0.75

# Monthly demand multipliers by trade (index 0 = January).
# Captures seasonal patterns: HVAC peaks in summer, Roofing peaks spring/fall,
# Plumbing steady with slight winter freeze-related uptick, Electrical even.
MONTHLY_FACTORS: dict[str, list[float]] = {
    #                 Jan   Feb   Mar   Apr   May   Jun   Jul   Aug   Sep   Oct   Nov   Dec
    "HVAC":        [0.70, 0.72, 0.80, 0.88, 1.00, 1.20, 1.30, 1.25, 1.00, 0.82, 0.88, 0.95],
    "Plumbing":    [1.10, 1.00, 0.92, 0.88, 0.88, 0.85, 0.82, 0.82, 0.88, 0.92, 1.00, 1.10],
    "Electrical":  [0.90, 0.90, 0.92, 0.95, 1.00, 1.05, 1.10, 1.08, 1.00, 0.95, 0.95, 0.92],
    "Roofing":     [0.65, 0.70, 0.88, 1.10, 1.20, 1.15, 1.05, 1.00, 1.10, 1.20, 0.88, 0.65],
}

TRADE_AVG_JOB_VALUE = {
    "HVAC": 480.0,
    "Plumbing": 360.0,
    "Electrical": 420.0,
    "Roofing": 7800.0,
}

JOB_STATUSES = ["scheduled", "in_progress", "completed", "cancelled"]


def _capacity_row(
    contractor: Contractor,
    day: date,
    rng: random.Random,
    record_type: str = "historical",
) -> dict:
    """Build one daily capacity record for a contractor.

    record_type='historical'  — full simulation: seasonal demand, weekend boost,
                                random weather events, backlog overflow counted.
    record_type='forecast'    — pre-committed bookings only: seasonal demand +
                                weekend boost scaled by FUTURE_BOOKING_RATE.
                                No weather events (future weather is unknown).
                                backlog_jobs is always 0.
    """
    techs = contractor.num_technicians
    daily_capacity = round(techs * JOBS_PER_TECH_PER_DAY)

    # Seasonal demand scales the contractor's baseline utilisation.
    seasonal_factor = MONTHLY_FACTORS[contractor.trade][day.month - 1]
    effective_util = contractor.sim_base_util * seasonal_factor

    # Weekends are busier — customers are home.
    if day.weekday() >= 5:
        effective_util *= WEEKEND_BOOST

    if record_type == "forecast":
        # Scale down to pre-committed fraction — rest of capacity still open.
        effective_util *= FUTURE_BOOKING_RATE
        weather_event = False
    else:
        # Historical: inject weather-driven demand spikes for sensitive trades.
        weather_event = (
            rng.random() < STORM_PROBABILITY
            and contractor.trade in ("Roofing", "Plumbing")
        )
        if weather_event:
            effective_util *= STORM_DEMAND_MULTIPLIER

    booked_pct = round(min(effective_util, 1.4), 3)
    scheduled_jobs = round(daily_capacity * booked_pct)
    available_job_slots = max(daily_capacity - scheduled_jobs, 0)
    # Overflow jobs pushed to next available date (only meaningful for historical rows).
    backlog_jobs = max(scheduled_jobs - daily_capacity, 0) if record_type == "historical" else 0

    return {
        "capacity_date": day.isoformat(),
        "contractor_id": contractor.contractor_id,
        "fleetsync_account_id": contractor.fleetsync_account_id,
        "business_name": contractor.business_name,
        "trade": contractor.trade,
        "num_technicians": techs,
        "daily_job_capacity": daily_capacity,
        "scheduled_jobs": scheduled_jobs,
        "available_job_slots": available_job_slots,
        "backlog_jobs": backlog_jobs,
        "booked_pct": booked_pct,
        "weather_event": weather_event,
        "record_type": record_type,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


def _dispatch_jobs_for_day(cap_row: dict, rng: random.Random) -> list[dict]:
    """Explode a capacity row into individual job records.

    Historical jobs get a realistic status mix (completed / cancelled / etc.).
    Forecast jobs are all 'scheduled' with a fixed average job value.
    """
    jobs = []
    trade = cap_row["trade"]
    avg_value = TRADE_AVG_JOB_VALUE[trade]
    record_type = cap_row.get("record_type", "historical")

    for j in range(cap_row["scheduled_jobs"]):
        if record_type == "forecast":
            status = "scheduled"
            job_value = avg_value  # fixed — no variance for pre-scheduled jobs
        else:
            status = rng.choices(JOB_STATUSES, weights=[0.35, 0.10, 0.50, 0.05])[0]
            job_value = round(avg_value * rng.uniform(0.6, 1.6), 2)

        jobs.append({
            "job_id": f"{cap_row['contractor_id']}-{cap_row['capacity_date']}-{j:03d}",
            "contractor_id": cap_row["contractor_id"],
            "fleetsync_account_id": cap_row["fleetsync_account_id"],
            "job_date": cap_row["capacity_date"],
            "trade": trade,
            "status": status,
            "record_type": record_type,
            "estimated_value_usd": job_value,
            "assigned_tech_id": f"TECH-{cap_row['contractor_id']}-{rng.randint(1, cap_row['num_technicians']):02d}",
        })
    return jobs


def generate(history_days: int, seed: int) -> tuple[list[dict], list[dict], list[dict]]:
    """Generate contractor, capacity, and job rows.

    Produces two windows of capacity + job data:
    * Historical  — `history_days` days ending yesterday. Full simulation with
                    seasonal demand, weekend boosts, and random weather events.
    * Forecast    — `FUTURE_DAYS` days starting today. Pre-committed bookings only
                    (FUTURE_BOOKING_RATE fraction of seasonal capacity). All job
                    statuses are 'scheduled'.
    """
    rng = random.Random(seed)
    today = date.today()

    contractors_rows = [c.as_dict() for c in CONTRACTORS]
    capacity_rows: list[dict] = []
    jobs_rows: list[dict] = []

    # --- Historical window (yesterday and back) ---
    for day_offset in range(history_days):
        day = today - timedelta(days=day_offset + 1)
        for contractor in CONTRACTORS:
            cap = _capacity_row(contractor, day, rng, record_type="historical")
            capacity_rows.append(cap)
            jobs_rows.extend(_dispatch_jobs_for_day(cap, rng))

    # --- Forecast window (today and forward) ---
    for day_offset in range(FUTURE_DAYS):
        day = today + timedelta(days=day_offset)
        for contractor in CONTRACTORS:
            cap = _capacity_row(contractor, day, rng, record_type="forecast")
            capacity_rows.append(cap)
            jobs_rows.extend(_dispatch_jobs_for_day(cap, rng))

    return contractors_rows, capacity_rows, jobs_rows


def _write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_local(contractors, capacity, jobs, out_dir: Path) -> dict[str, Path]:
    paths = {
        "contractors": out_dir / "fleetsync_contractors.csv",
        "technician_capacity": out_dir / "fleetsync_technician_capacity.csv",
        "dispatch_jobs": out_dir / "fleetsync_dispatch_jobs.csv",
    }
    _write_csv(contractors, paths["contractors"])
    _write_csv(capacity, paths["technician_capacity"])
    _write_csv(jobs, paths["dispatch_jobs"])
    return paths


def load_into_bigquery(paths: dict[str, Path], project: str, dataset: str, location: str) -> None:
    from google.cloud import bigquery  # lazy import so --local-only needs no GCP libs

    client = bigquery.Client(project=project, location=location)

    # Ensure the dataset exists (idempotent).
    ds_ref = bigquery.Dataset(f"{project}.{dataset}")
    ds_ref.location = location
    client.create_dataset(ds_ref, exists_ok=True)

    autodetect_load = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        autodetect=True,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    for table_name, path in paths.items():
        table_id = f"{project}.{dataset}.{table_name}"
        with path.open("rb") as fh:
            job = client.load_table_from_file(fh, table_id, job_config=autodetect_load)
        job.result()
        table = client.get_table(table_id)
        print(f"Loaded {table.num_rows} rows -> {table_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic FleetSync capacity data.")
    parser.add_argument(
        "--days", type=int, default=HISTORY_DAYS,
        help=f"Days of historical capacity to generate (default: {HISTORY_DAYS} = 2 years). "
             f"A {FUTURE_DAYS}-day forecast window of pre-scheduled jobs is always appended.",
    )
    parser.add_argument("--seed", type=int, default=7, help="Random seed for reproducibility.")
    parser.add_argument("--out-dir", default="data_out", help="Local output directory.")
    parser.add_argument("--load-bq", action="store_true", help="Load generated CSVs into BigQuery.")
    parser.add_argument("--local-only", action="store_true", help="Skip BigQuery load even if --load-bq is set.")
    args = parser.parse_args()

    contractors, capacity, jobs = generate(history_days=args.days, seed=args.seed)
    hist_count = sum(1 for r in capacity if r["record_type"] == "historical")
    fcast_count = sum(1 for r in capacity if r["record_type"] == "forecast")
    paths = write_local(contractors, capacity, jobs, Path(args.out_dir))
    print(
        f"Wrote: {len(contractors)} contractors, "
        f"{hist_count} historical + {fcast_count} forecast capacity rows, "
        f"{len(jobs)} dispatch jobs -> {args.out_dir}/"
    )

    if args.load_bq and not args.local_only:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        dataset = os.environ.get("BQ_DATASET", "fleetsync")
        location = os.environ.get("BQ_LOCATION", "US")
        if not project:
            raise SystemExit("GOOGLE_CLOUD_PROJECT env var is required for --load-bq. See .env.example.")
        load_into_bigquery(paths, project, dataset, location)


if __name__ == "__main__":
    main()
