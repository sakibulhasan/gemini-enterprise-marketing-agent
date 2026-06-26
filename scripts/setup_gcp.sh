#!/usr/bin/env bash
# =============================================================================
# setup_gcp.sh - one-time Google Cloud setup for the Cadence solution.
# Creates the GCS bucket, BigQuery dataset, enables APIs, and the staging bucket.
# Reads configuration from .env (copy .env.example -> .env first).
#
# Usage:
#   bash scripts/setup_gcp.sh
# =============================================================================
set -euo pipefail

# Load .env from repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a; source "$ROOT_DIR/.env"; set +a
else
  echo "ERROR: $ROOT_DIR/.env not found. Copy .env.example to .env and edit it." >&2
  exit 1
fi

: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT in .env}"
: "${GCS_BUCKET:?set GCS_BUCKET in .env}"
: "${BQ_DATASET:?set BQ_DATASET in .env}"
BQ_LOCATION="${BQ_LOCATION:-US}"
GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
STAGING_BUCKET="${AGENT_ENGINE_STAGING_BUCKET#gs://}"

echo "==> Setting active project: $GOOGLE_CLOUD_PROJECT"
gcloud config set project "$GOOGLE_CLOUD_PROJECT"

echo "==> Enabling required APIs"
gcloud services enable \
  aiplatform.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  discoveryengine.googleapis.com

echo "==> Creating GCS bucket for Google Ads export: gs://$GCS_BUCKET"
gcloud storage buckets create "gs://$GCS_BUCKET" \
  --location="$BQ_LOCATION" 2>/dev/null || echo "    (bucket already exists, skipping)"

if [[ -n "$STAGING_BUCKET" ]]; then
  echo "==> Creating Agent Engine staging bucket: gs://$STAGING_BUCKET"
  gcloud storage buckets create "gs://$STAGING_BUCKET" \
    --location="$GOOGLE_CLOUD_LOCATION" 2>/dev/null || echo "    (bucket already exists, skipping)"
fi

echo "==> Creating BigQuery dataset: $GOOGLE_CLOUD_PROJECT:$BQ_DATASET ($BQ_LOCATION)"
bq --location="$BQ_LOCATION" mk --dataset \
  --description "FleetSync capacity data for Cadence" \
  "$GOOGLE_CLOUD_PROJECT:$BQ_DATASET" 2>/dev/null || echo "    (dataset already exists, skipping)"

echo "==> Done. Next: load data and run the SQL (see README steps 3-4)."
