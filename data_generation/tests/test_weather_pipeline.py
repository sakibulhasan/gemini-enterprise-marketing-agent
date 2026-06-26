"""Tests for weather_pipeline.generate() — demand multipliers per forecast month."""

from datetime import date

from dateutil.relativedelta import relativedelta

import weather_pipeline


def _expected_forecast_months() -> list[str]:
    first_of_month = date.today().replace(day=1)
    return [
        (first_of_month + relativedelta(months=i)).strftime("%Y-%m")
        for i in range(weather_pipeline.NUM_FORECAST_MONTHS)
    ]


def test_one_row_per_forecast_month():
    df = weather_pipeline.generate()
    assert len(df) == weather_pipeline.NUM_FORECAST_MONTHS


def test_forecast_starts_at_current_month():
    df = weather_pipeline.generate()
    assert sorted(df["forecast_month"]) == sorted(_expected_forecast_months())


def test_storm_demand_multipliers_match_expected():
    row = weather_pipeline.generate().iloc[0]
    assert row["predicted_dominant_event"] == "SEVERE_STORMS"
    assert row["roofing_demand_multiplier"] == 1.8
    assert row["plumbing_demand_multiplier"] == 1.5
    assert row["electrician_demand_multiplier"] == 1.3
    assert row["hvac_demand_multiplier"] == 1.0


def test_schema_columns_present():
    df = weather_pipeline.generate()
    expected_cols = {field.name for field in weather_pipeline.SCHEMA}
    assert expected_cols.issubset(set(df.columns))
