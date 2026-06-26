"""
job_ledger_pipeline.py
======================

Pipeline #2 — builds the ``job_ledger`` table.

This pipeline produces the BOOKINGS history and the future schedule that tell the
optimizer how busy each contractor is.

What it models
--------------
Two distinct slices of data per contractor:

1. HISTORICAL jobs (status = COMPLETED)
   - One batch for every month from 2024-06 to 2026-06.
   - Each month's volume is 50%-85% of the contractor's capacity, giving the
     optimizer a realistic baseline of demand/throughput.

2. FUTURE jobs (status = SCHEDULED) for the next ``config.FUTURE_MONTHS`` months
   - One batch for every month AFTER the current month (relative to the run
     date), so the schedule always extends a few months into the future.
   - For each (contractor, month) the contractor is randomly flagged as either:
       * HEAVILY booked  -> ~90% of capacity already filled
       * LIGHTLY booked  -> ~30% of capacity already filled
   - This deliberate split is what lets the optimizer decide WHO can absorb more
     leads from an ad-budget raise (lightly booked) and who cannot (heavily
     booked / near capacity).

Output schema (BigQuery: job_ledger)
------------------------------------
- job_id                  STRING  (e.g. "JOB_1A2B3C4D")
- contractor_id           STRING  (FK -> contractors_master.contractor_id)
- service_category        STRING
- booking_date            DATE
- target_completion_month STRING  (YYYY-MM)
- job_status              STRING  (COMPLETED | SCHEDULED)
"""

import random
import uuid
from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta
from google.cloud import bigquery

import config
import gcp_utils

logger = config.get_logger(__name__)

SCHEMA = [
    bigquery.SchemaField("job_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("contractor_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("service_category", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("booking_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("target_completion_month", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("job_status", "STRING", mode="NULLABLE"),
]


def _new_job_id() -> str:
    """Return a short, unique job id like 'JOB_1A2B3C4D'."""
    return f"JOB_{uuid.uuid4().hex[:8].upper()}"


def _month_range(start: date, end: date) -> list[date]:
    """Return the first-of-month dates from ``start`` to ``end`` inclusive."""
    months, current = [], start
    while current <= end:
        months.append(current)
        current += relativedelta(months=1)
    return months


def generate(contractors_df: pd.DataFrame) -> pd.DataFrame:
    """Generate the full job ledger for every contractor (no GCP calls).

    Parameters
    ----------
    contractors_df :
        The contractor roster (needs contractor_id, service_category and
        max_monthly_capacity columns).
    """
    logger.info("Generating job ledger (historical COMPLETED + future SCHEDULED)...")
    jobs: list[dict] = []
    history_months = _month_range(config.HISTORY_START_DATE, config.HISTORY_END_DATE)

    # Future window: the next FUTURE_MONTHS months AFTER the current month, computed
    # relative to the run date so the schedule always extends into the future.
    first_of_month = date.today().replace(day=1)
    future_months = [
        first_of_month + relativedelta(months=i)
        for i in range(1, config.FUTURE_MONTHS + 1)
    ]

    for _, c in contractors_df.iterrows():
        cont_id = c["contractor_id"]
        category = c["service_category"]
        max_cap = int(c["max_monthly_capacity"])

        # --- 1. Historical COMPLETED jobs ----------------------------------
        for month in history_months:
            usage = random.uniform(0.50, 0.85)
            num_jobs = int(max_cap * usage)
            target_month_str = month.strftime("%Y-%m")
            for _ in range(num_jobs):
                # Booked 1-14 days before the completion month started.
                booking_date = month - relativedelta(days=random.randint(1, 14))
                jobs.append(
                    {
                        "job_id": _new_job_id(),
                        "contractor_id": cont_id,
                        "service_category": category,
                        "booking_date": booking_date,
                        "target_completion_month": target_month_str,
                        "job_status": "COMPLETED",
                    }
                )

        # --- 2. Future SCHEDULED jobs for the upcoming months -------------
        # Generate a forward schedule for each of the next FUTURE_MONTHS. Each
        # (contractor, month) is independently flagged heavily or lightly booked,
        # so utilization varies across both contractors and months.
        for month in future_months:
            target_month_str = month.strftime("%Y-%m")
            heavily_booked = random.choice([True, False])
            target_usage = 0.90 if heavily_booked else 0.30
            num_future_jobs = int(max_cap * target_usage)
            logger.info(
                "  %s: %s booked for %s (%d/%d capacity).",
                cont_id,
                "HEAVILY" if heavily_booked else "LIGHTLY",
                target_month_str,
                num_future_jobs,
                max_cap,
            )
            for _ in range(num_future_jobs):
                # Booked 1-30 days before the target month begins.
                booking_date = month - relativedelta(days=random.randint(1, 30))
                jobs.append(
                    {
                        "job_id": _new_job_id(),
                        "contractor_id": cont_id,
                        "service_category": category,
                        "booking_date": booking_date,
                        "target_completion_month": target_month_str,
                        "job_status": "SCHEDULED",
                    }
                )

    df = pd.DataFrame(jobs)
    # Normalise to real date objects so BigQuery maps the column cleanly to DATE.
    df["booking_date"] = pd.to_datetime(df["booking_date"]).dt.date
    logger.info("Generated %d total job records.", len(df))
    return df


def run(contractors_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Generate and load the job ledger.

    If ``contractors_df`` is not supplied (standalone execution), the contractor
    roster is read back from BigQuery.
    """
    if contractors_df is None:
        contractors_df = gcp_utils.fetch_contractors_from_bq()
    df = generate(contractors_df)
    gcp_utils.load_dataframe_to_bq(df, "job_ledger", SCHEMA)
    return df


if __name__ == "__main__":
    # Standalone:  python job_ledger_pipeline.py  (requires contractors_master to exist)
    gcp_utils.create_bq_dataset_if_not_exists()
    run()
