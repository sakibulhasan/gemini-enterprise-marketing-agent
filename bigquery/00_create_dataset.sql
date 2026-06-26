-- ============================================================================
-- 00_create_dataset.sql
-- ----------------------------------------------------------------------------
-- Creates the BigQuery dataset that holds all POC tables.
--
-- PROJECT_ID is substituted by setup_infra.sh at runtime. Run via:
--   export PROJECT_ID=your-project && ./bigquery/setup_infra.sh
-- Do NOT run this file directly with bq query (YOUR_PROJECT_ID won't be replaced).
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS `YOUR_PROJECT_ID.northwind_digital_jobs`
OPTIONS (
  location = 'US',
  description = 'Capacity-Aware Ad Budget Optimizer POC dataset'
);
