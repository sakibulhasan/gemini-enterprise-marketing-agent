-- =============================================================================
-- 02_create_tables.sql
-- Native BigQuery tables for FleetSync (Source 2).
--
-- Data model
-- ----------
-- The monthly jobs table replaces the previous daily technician_capacity and
-- dispatch_jobs tables.  Each row is a single committed job with full client
-- and job details.  Monthly capacity is always:
--
--     num_technicians × 10  (10 jobs per technician per month)
--
-- The ratio of committed jobs to monthly capacity drives the capacity verdict
-- in v_capacity_signals, which the Cadence agent reads when deciding whether
-- to approve a Google Ads budget increase.
--
-- NOTE: If you use the Python generator (--load-bq) it auto-detects the schema
-- and creates the table for you.  This file lets you create it explicitly if
-- you prefer IaC or want to review the canonical column definitions.
--
-- Placeholders: ${PROJECT}, ${DATASET}
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- Table 1: contractors
-- Static contractor profile (one row per contractor).
-- This is the join hub: contractor_id ties together the jobs table (BQ),
-- Google Ads recommendations (GCS), and weather lookups (lat/lon → REST API).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.contractors` (
  contractor_id           STRING  NOT NULL,   -- canonical join key across all sources
  business_name           STRING,
  trade                   STRING,             -- HVAC | Plumbing | Electrical | Roofing
  city                    STRING,
  state                   STRING,
  latitude                FLOAT64,            -- used by weather tool (Open-Meteo API)
  longitude               FLOAT64,
  timezone                STRING,
  num_technicians         INT64,              -- drives monthly_capacity = num_technicians × 10
  fleetsync_account_id    STRING,
  google_ads_customer_id  STRING
)
OPTIONS (description = 'Static contractor profiles — join hub across all data sources.');

-- ─────────────────────────────────────────────────────────────────────────────
-- Table 2: jobs
-- One row per committed job.  Monthly aggregations of this table drive the
-- capacity verdict the Cadence agent uses for budget recommendations.
--
-- Key fields for capacity analysis:
--   contractor_id  — which contractor is doing the work
--   year_month     — 'YYYY-MM' string for easy GROUP BY filtering
--   job_month      — DATE (first of month) used for BQ partition pruning
--   record_type    — 'historical' (past/current) or 'forecast' (future months)
--
-- Monthly capacity rule:
--   committed_jobs / (num_technicians × 10) = utilization_pct
--   If utilization_pct >= 1.0  → NO_CAPACITY  → HOLD the budget increase
--   If utilization_pct >= 0.70 → TIGHT_CAPACITY → PARTIAL increase only
--   Otherwise                  → HAS_CAPACITY   → APPROVE increase
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.jobs` (
  -- ── Identification ────────────────────────────────────────────────────────
  job_id              STRING  NOT NULL,     -- unique job identifier
  contractor_id       STRING  NOT NULL,     -- FK → contractors.contractor_id

  -- ── Time dimensions ──────────────────────────────────────────────────────
  year_month          STRING  NOT NULL,     -- 'YYYY-MM' e.g. '2026-06'; used for GROUP BY
  job_month           DATE    NOT NULL,     -- DATE '2026-06-01'; used for partition pruning

  -- ── Job classification ────────────────────────────────────────────────────
  trade               STRING,               -- HVAC | Plumbing | Electrical | Roofing
  job_type            STRING,               -- specific service type e.g. 'AC Repair'

  -- ── Client details ───────────────────────────────────────────────────────
  -- Synthetic data only — no real personal information is stored.
  client_name         STRING,               -- fictitious client full name
  client_address      STRING,               -- fictitious street address
  client_city         STRING,               -- city (matches contractor's metro)
  client_state        STRING,               -- US state abbreviation
  client_phone        STRING,               -- fictitious phone (555-format)

  -- ── Job outcome ───────────────────────────────────────────────────────────
  status              STRING,               -- scheduled | in_progress | completed | cancelled
  estimated_value_usd FLOAT64,              -- estimated invoice value in USD

  -- ── Data lineage ──────────────────────────────────────────────────────────
  record_type         STRING                -- 'historical' (past/current) | 'forecast' (future)
)
PARTITION BY job_month
OPTIONS (
  description = 'Monthly committed jobs per contractor.  '
                'Aggregate by (contractor_id, year_month) to compute '
                'utilization_pct for the Cadence budget-decision agent.'
);
