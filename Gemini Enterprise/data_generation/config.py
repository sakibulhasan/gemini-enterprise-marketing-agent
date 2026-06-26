"""
config.py
=========

Central configuration module for the Capacity-Aware Ad Budget Optimizer POC.

Every pipeline imports its settings from here so that there is a SINGLE place to
change the GCP project, the destination bucket, the BigQuery dataset, and the
business constants that drive the simulation.

Why a dedicated config module?
------------------------------
- Avoids "magic strings" scattered across multiple files.
- Makes the whole pipeline easy to point at a different project/bucket/dataset
  (e.g. dev vs. prod) by editing exactly one file.
- Keeps the logging format consistent across every pipeline.
"""

import logging

# ---------------------------------------------------------------------------
# GCP TARGETS  --  EDIT THESE THREE VALUES BEFORE RUNNING
# ---------------------------------------------------------------------------
# PROJECT_ID      : the Google Cloud project that owns BigQuery + GCS.
# GCS_BUCKET_NAME : an EXISTING Cloud Storage bucket for the JSON recommendations.
# BQ_DATASET_NAME : BigQuery dataset name; created automatically if missing.
PROJECT_ID = "project-e98a17cc-b3c1-4852-95f"
GCS_BUCKET_NAME = "northwind-digital-adsense"
BQ_DATASET_NAME = "northwind_digital_jobs"

# ---------------------------------------------------------------------------
# BUSINESS / SIMULATION CONSTANTS
# ---------------------------------------------------------------------------
# The four home-services verticals we simulate contractors for.
SERVICE_CATEGORIES = ["HVAC", "Plumbing", "Electrician", "Roofing"]

# The forecast/booking month the optimizer is reasoning about (the "future").
TARGET_MONTH = "2026-07"

# A fixed timestamp stamped onto every generated recommendation so output is
# deterministic and easy to eyeball during testing.
GENERATION_TIMESTAMP = "2026-06-23T14:30:00Z"

# Historical window for COMPLETED jobs in the job ledger (inclusive).
# We generate one "snapshot" of jobs for every month from start to end.
# The window is dynamic: it ends at the first of the CURRENT month (the month the
# script runs) and spans the two years prior, so the data is always recent.
from datetime import date  # noqa: E402  (kept here to live next to its usage)

from dateutil.relativedelta import relativedelta  # noqa: E402

HISTORY_END_DATE = date.today().replace(day=1)
HISTORY_START_DATE = HISTORY_END_DATE - relativedelta(years=2)


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger with the project-wide format.

    Using a shared factory guarantees every pipeline prints timestamps and log
    levels in exactly the same way, which keeps the orchestrated output readable.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(name)
