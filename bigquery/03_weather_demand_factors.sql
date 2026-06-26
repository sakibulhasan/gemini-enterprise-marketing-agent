-- ============================================================================
-- 03_weather_demand_factors.sql
-- ----------------------------------------------------------------------------
-- External demand signal: per-category demand multipliers driven by a weather
-- forecast for the target month. A severe-storm forecast spikes roofing /
-- plumbing demand, which the agent uses alongside capacity to recommend spend.
-- ============================================================================

CREATE TABLE IF NOT EXISTS `YOUR_PROJECT_ID.northwind_digital_jobs.weather_demand_factors` (
  forecast_month                STRING NOT NULL OPTIONS (description = 'YYYY-MM the forecast applies to'),
  region_zip                    STRING          OPTIONS (description = 'Region ZIP code'),
  predicted_dominant_event      STRING          OPTIONS (description = 'e.g. SEVERE_STORMS'),
  hvac_demand_multiplier        FLOAT64         OPTIONS (description = 'Demand multiplier for HVAC'),
  plumbing_demand_multiplier    FLOAT64         OPTIONS (description = 'Demand multiplier for Plumbing'),
  electrician_demand_multiplier FLOAT64         OPTIONS (description = 'Demand multiplier for Electrician'),
  roofing_demand_multiplier     FLOAT64         OPTIONS (description = 'Demand multiplier for Roofing')
)
OPTIONS (
  description = 'Weather-driven demand multipliers per service category.'
);
