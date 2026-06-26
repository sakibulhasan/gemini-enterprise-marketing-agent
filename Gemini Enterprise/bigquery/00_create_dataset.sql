-- ============================================================================
-- 00_create_dataset.sql
-- ----------------------------------------------------------------------------
-- Creates the BigQuery dataset that holds all POC tables.
--
-- The project id is already set below. Run with:
--   bq query --use_legacy_sql=false < bigquery/00_create_dataset.sql
-- (or paste into the BigQuery console).
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS `project-e98a17cc-b3c1-4852-95f.northwind_digital_jobs`
OPTIONS (
  location = 'US',
  description = 'Capacity-Aware Ad Budget Optimizer POC dataset'
);
