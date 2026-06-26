-- =============================================================================
-- 01_create_dataset.sql
-- Creates the FleetSync dataset that holds Source 2 (capacity / dispatch).
--
-- Source 1 (Google Ads recommendations) is NOT loaded into BigQuery here - it is
-- read directly from Cloud Storage by the agent's GCS connector. This keeps the
-- demo's connectors cleanly separated (Cloud Storage vs BigQuery vs REST API).
--
-- Placeholders (substituted by scripts/run_bigquery_sql.sh):
--   ${PROJECT}  -> your GCP project id        (e.g. my-proj)
--   ${DATASET}  -> BigQuery dataset name       (e.g. fleetsync)
--   ${LOCATION} -> dataset location            (e.g. US)
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS `${PROJECT}.${DATASET}`
OPTIONS (
  location = '${LOCATION}',
  description = 'FleetSync dispatch + capacity data for the Cadence agent (Source 2).'
);
