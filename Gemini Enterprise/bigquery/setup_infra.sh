#!/usr/bin/env bash
# ============================================================================
# setup_infra.sh
# ----------------------------------------------------------------------------
# One-shot provisioning of all GCP infrastructure for the POC:
#   1. Creates the BigQuery dataset + 3 tables from the DDL files in this folder.
#   2. Creates the GCS bucket for ad-recommendation JSON files.
#
# It substitutes YOUR_PROJECT_ID in the .sql files on the fly (the files on disk
# are left unchanged), so you only set values in ONE place: the env vars below.
#
# Prerequisites: gcloud + bq CLI installed and authenticated
#   gcloud auth login
#   gcloud auth application-default login
#
# Usage:
#   export PROJECT_ID="your-gcp-project-id"
#   export GCS_BUCKET_NAME="your-ad-recommendations-bucket"
#   export BUCKET_LOCATION="US"        # optional, defaults to US
#   ./bigquery/setup_infra.sh
# ============================================================================
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID, e.g. export PROJECT_ID=my-project}"
: "${GCS_BUCKET_NAME:?Set GCS_BUCKET_NAME, e.g. export GCS_BUCKET_NAME=my-bucket}"
BUCKET_LOCATION="${BUCKET_LOCATION:-US}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Setting active gcloud project to ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

echo "==> Enabling required APIs (idempotent)"
gcloud services enable bigquery.googleapis.com storage.googleapis.com

echo "==> Creating BigQuery dataset + tables"
for sql_file in \
  "${SCRIPT_DIR}/00_create_dataset.sql" \
  "${SCRIPT_DIR}/01_contractors_master.sql" \
  "${SCRIPT_DIR}/02_job_ledger.sql" \
  "${SCRIPT_DIR}/03_weather_demand_factors.sql"; do
  echo "    - Applying $(basename "${sql_file}")"
  sed "s/YOUR_PROJECT_ID/${PROJECT_ID}/g" "${sql_file}" \
    | bq query --use_legacy_sql=false
done

echo "==> Creating GCS bucket gs://${GCS_BUCKET_NAME} (skips if it exists)"
if gsutil ls -b "gs://${GCS_BUCKET_NAME}" >/dev/null 2>&1; then
  echo "    Bucket already exists, skipping."
else
  gsutil mb -l "${BUCKET_LOCATION}" "gs://${GCS_BUCKET_NAME}"
fi

echo "==> Infrastructure ready."
echo "    Next: run the data generation pipeline:"
echo "      cd data_generation && python run_pipeline.py"
