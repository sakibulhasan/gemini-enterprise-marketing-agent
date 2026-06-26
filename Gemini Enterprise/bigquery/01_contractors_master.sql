-- ============================================================================
-- 01_contractors_master.sql
-- ----------------------------------------------------------------------------
-- Contractor catalog with operational capacity.
--   max_monthly_capacity = num_technicians * jobs_per_tech_month
--
-- contractor_id is the logical primary key every other table joins against.
-- ============================================================================

CREATE TABLE IF NOT EXISTS `project-e98a17cc-b3c1-4852-95f.northwind_digital_jobs.contractors_master` (
  contractor_id        STRING  NOT NULL OPTIONS (description = 'Logical primary key, e.g. CONT_HVAC_01'),
  contractor_name      STRING           OPTIONS (description = 'Company name'),
  service_category     STRING           OPTIONS (description = 'HVAC | Plumbing | Electrician | Roofing'),
  num_technicians      INT64            OPTIONS (description = 'Headcount (2-5)'),
  jobs_per_tech_month  INT64            OPTIONS (description = 'Jobs each technician can complete per month'),
  max_monthly_capacity INT64            OPTIONS (description = 'num_technicians * jobs_per_tech_month')
)
OPTIONS (
  description = 'Home-services contractors and their monthly job capacity.'
);
