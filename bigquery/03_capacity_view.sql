-- =============================================================================
-- 03_capacity_view.sql
-- Monthly capacity decision layer: v_capacity_signals
--
-- Purpose
-- -------
-- Combines the jobs table with the contractors profile to produce one row per
-- contractor showing:
--   * How full the contractor is THIS month (committed jobs vs. monthly capacity)
--   * How pre-booked the next 3 months look (forecast jobs already on the books)
--   * The 6-month historical average (what "normal" looks like for this contractor)
--   * A derived capacity_verdict and suggested_action for the Cadence agent
--
-- Capacity rule
-- -------------
-- monthly_capacity = num_technicians × 10  (10 jobs per technician per month)
-- utilization_pct  = committed_jobs / monthly_capacity
--
--   utilization_pct >= 1.0  (100%+) → NO_CAPACITY    → HOLD budget increase
--   utilization_pct >= 0.70 (70–99%) → TIGHT_CAPACITY → PARTIAL increase only
--   utilization_pct <  0.70 (< 70%)  → HAS_CAPACITY   → APPROVE full increase
--
-- The agent reads this view via the BigQuery connector.  Google Ads
-- recommendations (Source 1) live in Cloud Storage and are joined by the agent
-- using contractor_id as the cross-source key.
--
-- Placeholders: ${PROJECT}, ${DATASET}
-- =============================================================================

CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.v_capacity_signals` AS
WITH

-- ────────────────────────────────────────────────────────────────────────────
-- CTE 1: monthly_committed
-- Aggregate the jobs table to one row per (contractor, month).
-- This is the foundation for all subsequent capacity calculations.
-- ────────────────────────────────────────────────────────────────────────────
monthly_committed AS (
  SELECT
    contractor_id,
    year_month,                             -- 'YYYY-MM' — the grouping key
    record_type,                            -- 'historical' or 'forecast'
    COUNT(*)                          AS committed_jobs,           -- total jobs committed
    ROUND(SUM(estimated_value_usd), 2) AS committed_revenue_usd   -- total estimated revenue
  FROM `${PROJECT}.${DATASET}.jobs`
  GROUP BY contractor_id, year_month, record_type
),

-- ────────────────────────────────────────────────────────────────────────────
-- CTE 2: current_month
-- Snapshot of committed jobs in the month that CURRENT_DATE() falls in.
-- This is the primary signal the agent uses: "how full is this contractor
-- right now, in the current billing/planning month?"
-- ────────────────────────────────────────────────────────────────────────────
current_month AS (
  SELECT
    contractor_id,
    committed_jobs,
    committed_revenue_usd
  FROM monthly_committed
  WHERE year_month = FORMAT_DATE('%Y-%m', CURRENT_DATE())  -- e.g. '2026-06'
    AND record_type = 'historical'  -- current month rows come from historical data
),

-- ────────────────────────────────────────────────────────────────────────────
-- CTE 3: next_3m_forecast
-- Jobs already pre-booked for the next 3 calendar months (forecast rows).
-- A contractor whose forecast months are already 80%+ full should not take
-- on more leads even if today looks fine.
-- ────────────────────────────────────────────────────────────────────────────
next_3m_forecast AS (
  SELECT
    contractor_id,
    SUM(committed_jobs)             AS total_next_3m_jobs,           -- total jobs across 3 months
    ROUND(AVG(committed_jobs), 1)   AS avg_next_3m_jobs_per_month    -- average per month
  FROM monthly_committed
  WHERE record_type = 'forecast'
    -- strictly after the current month
    AND year_month > FORMAT_DATE('%Y-%m', CURRENT_DATE())
    -- up to and including 3 months from now
    AND year_month <= FORMAT_DATE('%Y-%m', DATE_ADD(CURRENT_DATE(), INTERVAL 3 MONTH))
  GROUP BY contractor_id
),

-- ────────────────────────────────────────────────────────────────────────────
-- CTE 4: historical_baseline
-- Average jobs per month over the last 6 completed months.
-- Excludes the current month (still in progress) so the average reflects
-- only fully-closed months.  This is the "what normal looks like" signal.
-- ────────────────────────────────────────────────────────────────────────────
historical_baseline AS (
  SELECT
    contractor_id,
    ROUND(AVG(committed_jobs), 1)   AS avg_6m_jobs_per_month,  -- 6-month rolling average
    COUNT(DISTINCT year_month)      AS months_of_data           -- how many months contributed
  FROM monthly_committed
  WHERE record_type = 'historical'
    -- exclude current month (not yet complete)
    AND year_month < FORMAT_DATE('%Y-%m', CURRENT_DATE())
    -- look back at most 6 months
    AND year_month >= FORMAT_DATE('%Y-%m', DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH))
  GROUP BY contractor_id
)

-- ────────────────────────────────────────────────────────────────────────────
-- Final SELECT: join all CTEs with the contractors profile.
-- SAFE_DIVIDE guards against division by zero if num_technicians is 0.
-- COALESCE converts NULL (no rows) to sensible defaults (0 or 0.0).
-- ────────────────────────────────────────────────────────────────────────────
SELECT
  -- ── Contractor identity ─────────────────────────────────────────────────────────
  prof.contractor_id,
  prof.business_name,
  prof.trade,
  prof.city,
  prof.state,

  -- ── Capacity parameters ──────────────────────────────────────────────────────
  prof.num_technicians,
  (prof.num_technicians * 10)                          AS monthly_capacity,
  -- monthly_capacity = num_technicians × 10 jobs/tech/month

  -- ── Current month ────────────────────────────────────────────────────────────
  FORMAT_DATE('%Y-%m', CURRENT_DATE())                 AS current_year_month,
  COALESCE(cm.committed_jobs, 0)                       AS current_month_jobs,
  COALESCE(cm.committed_revenue_usd, 0.0)              AS current_month_revenue_usd,
  -- utilization_pct: 1.0 = fully booked, 0.70 = 70% booked, etc.
  ROUND(
    SAFE_DIVIDE(
      COALESCE(cm.committed_jobs, 0),
      prof.num_technicians * 10
    ), 3
  )                                                    AS current_utilization_pct,
  -- available_slots: how many more jobs can be taken on this month
  GREATEST(
    (prof.num_technicians * 10) - COALESCE(cm.committed_jobs, 0),
    0
  )                                                    AS available_slots,

  -- ── Next 3 months (forecast window) ──────────────────────────────────────────
  COALESCE(n3.total_next_3m_jobs, 0)                   AS total_next_3m_jobs,
  COALESCE(n3.avg_next_3m_jobs_per_month, 0.0)         AS avg_next_3m_jobs_per_month,
  ROUND(
    SAFE_DIVIDE(
      COALESCE(n3.avg_next_3m_jobs_per_month, 0),
      prof.num_technicians * 10
    ), 3
  )                                                    AS avg_next_3m_utilization_pct,

  -- ── 6-month historical baseline ──────────────────────────────────────────────
  COALESCE(hb.avg_6m_jobs_per_month, 0.0)              AS avg_6m_jobs_per_month,
  ROUND(
    SAFE_DIVIDE(
      COALESCE(hb.avg_6m_jobs_per_month, 0),
      prof.num_technicians * 10
    ), 3
  )                                                    AS avg_6m_utilization_pct,
  COALESCE(hb.months_of_data, 0)                       AS months_of_data,

  -- ── Capacity verdict (drives the agent's HOLD / PARTIAL / APPROVE logic) ───
  CASE
    WHEN COALESCE(cm.committed_jobs, 0) >= (prof.num_technicians * 10)
      THEN 'NO_CAPACITY'      -- 100%+ booked: no room for more leads at all
    WHEN ROUND(SAFE_DIVIDE(
           COALESCE(cm.committed_jobs, 0),
           prof.num_technicians * 10
         ), 3) >= 0.70
      THEN 'TIGHT_CAPACITY'   -- 70–99% booked: increasing budget is risky
    ELSE
      'HAS_CAPACITY'          -- < 70% booked: comfortable headroom for more leads
  END AS capacity_verdict,

  CASE
    WHEN COALESCE(cm.committed_jobs, 0) >= (prof.num_technicians * 10)
      THEN 'HOLD'             -- fully booked: do not increase spend
    WHEN ROUND(SAFE_DIVIDE(
           COALESCE(cm.committed_jobs, 0),
           prof.num_technicians * 10
         ), 3) >= 0.70
      THEN 'PARTIAL_INCREASE' -- nearly full: cautious, limited increase
    ELSE
      'APPROVE_INCREASE'      -- has headroom: approve the full recommended increase
  END AS suggested_action

FROM `${PROJECT}.${DATASET}.contractors` AS prof
LEFT JOIN current_month    AS cm ON prof.contractor_id = cm.contractor_id
LEFT JOIN next_3m_forecast  AS n3 ON prof.contractor_id = n3.contractor_id
LEFT JOIN historical_baseline AS hb ON prof.contractor_id = hb.contractor_id;
