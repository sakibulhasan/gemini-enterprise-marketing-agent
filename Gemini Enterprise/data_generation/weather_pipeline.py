"""
weather_pipeline.py
===================

Pipeline #3 — builds the ``weather_demand_factors`` table.

What it models
--------------
The EXTERNAL demand signal. A weather forecast predicts SEVERE_STORMS in a region,
which changes how much demand each service category will see. These multipliers
let the optimizer boost ad spend where storm-driven demand is expected to spike.

Forecasts are generated for the CURRENT month (the month the script runs) plus
the next few months, so the table always covers the period the optimizer reasons
about (including the future TARGET_MONTH used by the job ledger).

Multiplier rationale for a severe-storm forecast:
- HVAC        x1.0  (neutral — storms don't drive much HVAC work)
- Plumbing    x1.5  (flooding / drainage issues)
- Electrician x1.3  (power outages, electrical faults)
- Roofing     x1.8  (wind / hail damage — highest impact)

Output schema (BigQuery: weather_demand_factors)
------------------------------------------------
- forecast_month             STRING (YYYY-MM)
- region_zip                 STRING
- predicted_dominant_event   STRING
- hvac_demand_multiplier     FLOAT
- plumbing_demand_multiplier FLOAT
- electrician_demand_multiplier FLOAT
- roofing_demand_multiplier  FLOAT

This is a single-row reference table for the POC.
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
from google.cloud import bigquery

import config
import gcp_utils

logger = config.get_logger(__name__)

# How many months of forecast to generate: the current month plus the next
# (NUM_FORECAST_MONTHS - 1) months.
NUM_FORECAST_MONTHS = 3

SCHEMA = [
    bigquery.SchemaField("forecast_month", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("region_zip", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("predicted_dominant_event", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("hvac_demand_multiplier", "FLOAT", mode="NULLABLE"),
    bigquery.SchemaField("plumbing_demand_multiplier", "FLOAT", mode="NULLABLE"),
    bigquery.SchemaField("electrician_demand_multiplier", "FLOAT", mode="NULLABLE"),
    bigquery.SchemaField("roofing_demand_multiplier", "FLOAT", mode="NULLABLE"),
]


def generate() -> pd.DataFrame:
    """Generate weather demand factors for the current month and the next few
    months (one row per forecast month). No GCP calls."""
    first_of_month = date.today().replace(day=1)
    forecast_months = [
        (first_of_month + relativedelta(months=i)).strftime("%Y-%m")
        for i in range(NUM_FORECAST_MONTHS)
    ]
    logger.info("Generating weather demand factors for %s...", ", ".join(forecast_months))

    rows = [
        {
            "forecast_month": month,
            "region_zip": "75001",
            "predicted_dominant_event": "SEVERE_STORMS",
            "hvac_demand_multiplier": 1.0,
            "plumbing_demand_multiplier": 1.5,
            "electrician_demand_multiplier": 1.3,
            "roofing_demand_multiplier": 1.8,
        }
        for month in forecast_months
    ]
    df = pd.DataFrame(rows)
    logger.info("Generated %d weather record(s).", len(df))
    return df


def run() -> pd.DataFrame:
    """Generate and load the weather demand factors into BigQuery."""
    df = generate()
    gcp_utils.load_dataframe_to_bq(df, "weather_demand_factors", SCHEMA)
    return df


if __name__ == "__main__":
    # Standalone:  python weather_pipeline.py
    gcp_utils.create_bq_dataset_if_not_exists()
    run()
