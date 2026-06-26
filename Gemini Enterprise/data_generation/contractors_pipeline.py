"""
contractors_pipeline.py
========================

Pipeline #1 — builds the ``contractors_master`` table.

This is the FOUNDATIONAL pipeline: every other pipeline keys off the contractor
identities produced here. It must run first.

What it models
--------------
A roster of home-services companies. Each contractor's *operational capacity*
(how many jobs they can physically complete in a month) is derived from headcount:

    max_monthly_capacity = num_technicians * jobs_per_tech_month

That capacity number is the heart of the "capacity-aware" optimizer: there is no
point raising a contractor's ad budget if they are already at capacity.

Output schema (BigQuery: contractors_master)
--------------------------------------------
- contractor_id        STRING   (e.g. "CONT_HVAC_01")  -- logical primary key
- contractor_name      STRING
- service_category     STRING   (HVAC | Plumbing | Electrician | Roofing)
- num_technicians      INTEGER  (random 2-5)
- jobs_per_tech_month  INTEGER  (constant 10)
- max_monthly_capacity INTEGER  (num_technicians * jobs_per_tech_month)

Exactly 12 contractors are generated: 3 per service category.
"""

import random

import pandas as pd
from google.cloud import bigquery

import config
import gcp_utils

logger = config.get_logger(__name__)

# Explicit BigQuery schema. contractor_id is REQUIRED because it is the key that
# every downstream table joins against.
SCHEMA = [
    bigquery.SchemaField("contractor_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("contractor_name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("service_category", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("num_technicians", "INTEGER", mode="NULLABLE"),
    bigquery.SchemaField("jobs_per_tech_month", "INTEGER", mode="NULLABLE"),
    bigquery.SchemaField("max_monthly_capacity", "INTEGER", mode="NULLABLE"),
]

JOBS_PER_TECH_MONTH = 10  # business constant: each technician handles 10 jobs/month


def generate() -> pd.DataFrame:
    """Generate the 12-row contractor roster as a DataFrame (no GCP calls)."""
    logger.info("Generating contractors (3 per category)...")
    rows = []

    for category in config.SERVICE_CATEGORIES:
        for i in range(1, 4):  # three contractors per category: 01, 02, 03
            num_technicians = random.randint(2, 5)
            rows.append(
                {
                    "contractor_id": f"CONT_{category.upper()}_{i:02d}",
                    "contractor_name": f"{category} Experts {i}",
                    "service_category": category,
                    "num_technicians": num_technicians,
                    "jobs_per_tech_month": JOBS_PER_TECH_MONTH,
                    # Derived capacity — the key signal for the optimizer.
                    "max_monthly_capacity": num_technicians * JOBS_PER_TECH_MONTH,
                }
            )

    df = pd.DataFrame(rows)
    logger.info("Generated %d contractors.", len(df))
    return df


def run() -> pd.DataFrame:
    """Generate the data and load it into BigQuery. Returns the DataFrame so the
    orchestrator can pass it directly to the dependent pipelines without a
    round-trip to BigQuery."""
    df = generate()
    gcp_utils.load_dataframe_to_bq(df, "contractors_master", SCHEMA)
    return df


if __name__ == "__main__":
    # Allow this pipeline to be executed on its own:  python contractors_pipeline.py
    gcp_utils.create_bq_dataset_if_not_exists()
    run()
