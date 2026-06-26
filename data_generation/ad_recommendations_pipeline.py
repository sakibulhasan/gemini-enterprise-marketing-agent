"""
ad_recommendations_pipeline.py
==============================

Pipeline #4 — generates Ad Recommendation JSON documents and streams them to
Google Cloud Storage (GCS).

What it models
--------------
For each contractor, an ad-budget recommendation produced by the optimizer. In
the POC these are mock "BUDGET_RAISE" suggestions with projected impact metrics.
They land in GCS (not BigQuery) because they represent semi-structured,
document-style output that downstream systems / Gemini Enterprise can read.

One recommendation per contractor is generated for the CURRENT month and the
NEXT month, computed relative to the date the script runs.

GCS layout (Hive-style partitioning by year/month, derived from the target month)
--------------------------------------------------------------------------------
    gs://[BUCKET]/ad_recommendations/year=YYYY/month=MM/rec_[CONTRACTOR_ID].json

JSON document shape
-------------------
{
  "recommendation_id": "rec_202607_CONT_HVAC_01",
  "generated_timestamp": "2026-06-23T14:30:00Z",
  "target_month": "2026-07",
  "service_category": "HVAC",
  "contractor_id": "CONT_HVAC_01",
  "recommendation_type": "BUDGET_RAISE",
  "current_monthly_budget": 200.00,
  "recommended_budget_increase": 50.00,
  "metrics_impact": {
    "estimated_additional_clicks": 25,
    "estimated_additional_cost": 50.00,
    "historical_conversion_rate": 0.12,
    "projected_new_leads": 3
  },
  "status": "PENDING_REVIEW"
}
"""

import json
import random
from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta

import config
import gcp_utils

logger = config.get_logger(__name__)


def _target_months() -> list[str]:
    """Return the current and next month (YYYY-MM) relative to the run date."""
    first_of_month = date.today().replace(day=1)
    return [
        (first_of_month + relativedelta(months=i)).strftime("%Y-%m")
        for i in range(2)
    ]


def build_recommendation(
    contractor_id: str, service_category: str, target_month: str
) -> dict:
    """Build a single recommendation document for one contractor and month.

    The numeric fields are randomised within realistic ranges so the dataset
    looks plausible while remaining obviously synthetic.
    """
    return {
        "recommendation_id": f"rec_{target_month.replace('-', '')}_{contractor_id}",
        "generated_timestamp": config.GENERATION_TIMESTAMP,
        "target_month": target_month,
        "service_category": service_category,
        "contractor_id": contractor_id,
        "recommendation_type": "BUDGET_RAISE",
        "current_monthly_budget": round(random.uniform(100.0, 500.0), 2),
        "recommended_budget_increase": round(random.uniform(50.0, 150.0), 2),
        "metrics_impact": {
            "estimated_additional_clicks": random.randint(10, 50),
            "estimated_additional_cost": round(random.uniform(50.0, 150.0), 2),
            "historical_conversion_rate": round(random.uniform(0.05, 0.20), 2),
            "projected_new_leads": random.randint(1, 10),
        },
        "status": "PENDING_REVIEW",
    }


def run(contractors_df: pd.DataFrame | None = None) -> None:
    """Generate one recommendation per contractor for the current and next month
    and upload each as a JSON object to GCS.

    If ``contractors_df`` is not supplied (standalone execution), the contractor
    roster is read back from BigQuery.
    """
    if contractors_df is None:
        contractors_df = gcp_utils.fetch_contractors_from_bq()

    storage_client = gcp_utils.get_storage_client()
    bucket = storage_client.bucket(config.GCS_BUCKET_NAME)

    # The bucket must already exist; warn early with a clear message if not.
    if not bucket.exists():
        logger.warning(
            "Bucket '%s' not found. Create it before running this pipeline.",
            config.GCS_BUCKET_NAME,
        )

    target_months = _target_months()
    for _, c in contractors_df.iterrows():
        cont_id = c["contractor_id"]
        category = c["service_category"]

        for target_month in target_months:
            payload = build_recommendation(cont_id, category, target_month)
            # Hive-style partition path derived from the target month (YYYY-MM).
            year, month = target_month.split("-")
            blob_path = (
                f"ad_recommendations/year={year}/month={month}/rec_{cont_id}.json"
            )

            logger.info("Uploading JSON for %s (%s)...", cont_id, target_month)
            bucket.blob(blob_path).upload_from_string(
                data=json.dumps(payload, indent=2),
                content_type="application/json",
            )
            logger.info("  -> gs://%s/%s", config.GCS_BUCKET_NAME, blob_path)


if __name__ == "__main__":
    # Standalone:  python ad_recommendations_pipeline.py  (requires contractors_master)
    run()
