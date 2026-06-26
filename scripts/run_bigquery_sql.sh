#!/usr/bin/env bash
# =============================================================================
# run_bigquery_sql.sh - substitute ${PROJECT}/${DATASET}/${LOCATION} placeholders
# in the bigquery/*.sql files and execute them in order.
#
# Reads configuration from .env. Runs:
#   01_create_dataset.sql
#   03_capacity_view.sql        (capacity-only analytic view)
#
# 02_create_tables.sql is OPTIONAL - the Python loader autodetects + creates the
# native FleetSync tables. Pass --with-tables to run it explicitly.
#
# NOTE: Source 1 (Google Ads recommendations) is read directly from Cloud Storage
# by the agent, so there is no external-table SQL to run here.
#
# Usage:
#   bash scripts/run_bigquery_sql.sh [--with-tables]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
SQL_DIR="$ROOT_DIR/bigquery"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a; source "$ROOT_DIR/.env"; set +a
else
  echo "ERROR: $ROOT_DIR/.env not found. Copy .env.example to .env and edit it." >&2
  exit 1
fi

: "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT in .env}"
: "${BQ_DATASET:?set BQ_DATASET in .env}"
BQ_LOCATION="${BQ_LOCATION:-US}"

run_sql_file() {
  local file="$1"
  echo "==> Running $(basename "$file")"
  sed \
    -e "s|\${PROJECT}|${GOOGLE_CLOUD_PROJECT}|g" \
    -e "s|\${DATASET}|${BQ_DATASET}|g" \
    -e "s|\${LOCATION}|${BQ_LOCATION}|g" \
    "$file" | bq --location="$BQ_LOCATION" query --use_legacy_sql=false
}

run_sql_file "$SQL_DIR/01_create_dataset.sql"

if [[ "${1:-}" == "--with-tables" ]]; then
  run_sql_file "$SQL_DIR/02_create_tables.sql"
fi

run_sql_file "$SQL_DIR/03_capacity_view.sql"

echo "==> BigQuery objects created. Quick check:"
bq --location="$BQ_LOCATION" query --use_legacy_sql=false \
  "SELECT contractor_id, business_name, booked_pct, backlog_days,
          capacity_verdict, suggested_action
   FROM \`${GOOGLE_CLOUD_PROJECT}.${BQ_DATASET}.v_capacity_signals\`
   ORDER BY booked_pct DESC LIMIT 10"
