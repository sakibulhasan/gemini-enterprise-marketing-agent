"""Generate a synthetic Google Ads "budget" recommendations export and (optionally)
upload it to Cloud Storage.

This mirrors how Northwind Digital would land a daily Google Ads export in GCS:
one newline-delimited JSON file (JSONL) per run, partitioned by date. Each row
is a *budget recommendation* Google surfaced for a campaign - i.e. Google
nudging "increase this campaign's budget".

The schema is intentionally close to the Google Ads API ``Recommendation`` +
``CampaignBudget`` resources so the direct Cloud Storage connector and the
Cadence agent feel realistic.

Usage
-----
    # local only (writes to ./data_out)
    python -m data_generation.generate_google_ads_data --days 1 --local-only

    # generate and upload to GCS (reads GCS_BUCKET / GCS_ADS_PREFIX from env)
    python -m data_generation.generate_google_ads_data --days 1 --upload
"""

from __future__ import annotations

import argparse
import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from config.contractors import CONTRACTORS, Contractor

# Micros are how Google Ads represents money: 1 unit = 1_000_000 micros.
MICROS = 1_000_000

# ---- Generation constants (code-only — not in .env) ----
# How much Google recommends increasing the daily budget (as a fraction).
BUDGET_BUMP_PCT: float = 0.35
# Share of impressions estimated to be lost due to budget constraint.
LOST_IMPRESSION_SHARE: float = 0.28
# Estimated extra clicks per extra dollar of daily budget.
CLICKS_PER_DOLLAR: float = 1.2
# Estimated conversion rate for the incremental clicks.
CONVERSION_RATE: float = 0.10

CAMPAIGN_TEMPLATES = {
    "HVAC": ["AC Repair - Search", "Heating Install - Search"],
    "Plumbing": ["Emergency Plumbing - Search", "Water Heater - Search"],
    "Electrical": ["Panel Upgrade - Search", "Electrician Near Me - Search"],
    "Roofing": ["Roof Replacement - Search", "Storm Damage Repair - Search"],
}


def _money_micros(dollars: float) -> int:
    return int(round(dollars * MICROS))


def _recommendation_rows(contractor: Contractor, run_date: date, rng: random.Random) -> Iterator[dict]:
    """Yield one budget recommendation row per campaign for a contractor."""
    for i, campaign_name in enumerate(CAMPAIGN_TEMPLATES[contractor.trade]):
        campaign_id = f"{contractor.google_ads_customer_id}-{i+1:03d}"

        current_daily = contractor.current_daily_budget_usd
        recommended_daily = round(current_daily * (1 + BUDGET_BUMP_PCT), 2)
        budget_increase = round(recommended_daily - current_daily, 2)

        est_incr_clicks = int(round(budget_increase * CLICKS_PER_DOLLAR))
        est_incr_conversions = round(est_incr_clicks * CONVERSION_RATE, 2)

        yield {
            "export_date": run_date.isoformat(),
            "contractor_id": contractor.contractor_id,
            "customer_id": contractor.google_ads_customer_id,
            "account_name": contractor.business_name,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "recommendation_id": f"{contractor.google_ads_customer_id}-{campaign_id}-{run_date.isoformat()}",
            "recommendation_type": "CAMPAIGN_BUDGET",
            "current_daily_budget_micros": _money_micros(current_daily),
            "recommended_daily_budget_micros": _money_micros(recommended_daily),
            "recommended_budget_increase_micros": _money_micros(budget_increase),
            "current_daily_budget_usd": float(current_daily),
            "recommended_daily_budget_usd": float(recommended_daily),
            "recommended_budget_increase_usd": float(budget_increase),
            "lost_impression_share_budget": LOST_IMPRESSION_SHARE,
            "estimated_incremental_clicks": est_incr_clicks,
            "estimated_incremental_conversions": est_incr_conversions,
            "currency_code": "USD",
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }


def generate(days: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    today = date.today()
    rows: list[dict] = []
    for day_offset in range(days):
        run_date = today - timedelta(days=day_offset)
        for contractor in CONTRACTORS:
            rows.extend(_recommendation_rows(contractor, run_date, rng))
    return rows


def write_local(rows: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    out_path = out_dir / f"google_ads_recommendations_{stamp}.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return out_path


def upload_to_gcs(local_path: Path, bucket_name: str, prefix: str) -> str:
    from google.cloud import storage  # imported lazily so --local-only needs no GCP libs

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    # Partition by date so BigQuery / Gemini Enterprise can pick it up incrementally.
    blob_name = f"{prefix}/dt={date.today().isoformat()}/{local_path.name}"
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(local_path), content_type="application/json")
    return f"gs://{bucket_name}/{blob_name}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic Google Ads budget recommendations.")
    parser.add_argument("--days", type=int, default=1, help="Number of days of history to generate.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    parser.add_argument("--out-dir", default="data_out", help="Local output directory.")
    parser.add_argument("--upload", action="store_true", help="Upload the file to GCS after writing locally.")
    parser.add_argument("--local-only", action="store_true", help="Skip GCS upload even if --upload is set.")
    args = parser.parse_args()

    rows = generate(days=args.days, seed=args.seed)
    local_path = write_local(rows, Path(args.out_dir))
    print(f"Wrote {len(rows)} recommendation rows -> {local_path}")

    if args.upload and not args.local_only:
        bucket = os.environ.get("GCS_BUCKET")
        prefix = os.environ.get("GCS_ADS_PREFIX", "google_ads_export")
        if not bucket:
            raise SystemExit("GCS_BUCKET env var is required for --upload. See .env.example.")
        uri = upload_to_gcs(local_path, bucket, prefix)
        print(f"Uploaded -> {uri}")


if __name__ == "__main__":
    main()
