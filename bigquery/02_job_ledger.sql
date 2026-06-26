-- ============================================================================
-- 02_job_ledger.sql
-- ----------------------------------------------------------------------------
-- Bookings ledger: historical COMPLETED jobs (2024-06 -> 2026-06) plus future
-- SCHEDULED jobs for the target month (2026-07). Used to compute utilization:
--   utilization = scheduled_jobs(target_month) / max_monthly_capacity
--
-- Partitioned by booking_date and clustered by contractor_id for efficient
-- utilization queries.
-- ============================================================================

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT_ID.northwind_digital_jobs.job_ledger` (
  job_id                  STRING NOT NULL OPTIONS (description = 'Unique job id, e.g. JOB_1A2B3C4D'),
  contractor_id           STRING          OPTIONS (description = 'FK -> contractors_master.contractor_id'),
  service_category        STRING          OPTIONS (description = 'Matches the contractor category'),
  booking_date            DATE            OPTIONS (description = 'Date the job was booked'),
  target_completion_month STRING          OPTIONS (description = 'YYYY-MM the job is scheduled to complete'),
  job_status              STRING          OPTIONS (description = 'COMPLETED | SCHEDULED | IN_PROGRESS | CANCELLED')
)
PARTITION BY booking_date
CLUSTER BY contractor_id
OPTIONS (
  description = 'Historical and scheduled jobs per contractor.'
);
