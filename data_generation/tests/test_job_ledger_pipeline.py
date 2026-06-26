"""Tests for job_ledger_pipeline.generate() — historical + future bookings."""

from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta

import config
import job_ledger_pipeline


def _sample_contractors() -> pd.DataFrame:
    """A minimal contractor roster with the columns generate() relies on."""
    return pd.DataFrame(
        [
            {
                "contractor_id": "CONT_HVAC_01",
                "service_category": "HVAC",
                "max_monthly_capacity": 30,
            },
            {
                "contractor_id": "CONT_ROOFING_01",
                "service_category": "Roofing",
                "max_monthly_capacity": 40,
            },
        ]
    )


def _expected_future_months() -> list[str]:
    first_of_month = date.today().replace(day=1)
    return [
        (first_of_month + relativedelta(months=i)).strftime("%Y-%m")
        for i in range(1, config.FUTURE_MONTHS + 1)
    ]


def test_generates_completed_and_scheduled_jobs():
    df = job_ledger_pipeline.generate(_sample_contractors())
    assert set(df["job_status"].unique()) == {"COMPLETED", "SCHEDULED"}


def test_future_schedule_spans_configured_months():
    df = job_ledger_pipeline.generate(_sample_contractors())
    scheduled = df[df["job_status"] == "SCHEDULED"]
    months = sorted(scheduled["target_completion_month"].unique())
    assert months == sorted(_expected_future_months())


def test_future_months_are_after_current_month():
    df = job_ledger_pipeline.generate(_sample_contractors())
    scheduled = df[df["job_status"] == "SCHEDULED"]
    current_month = date.today().strftime("%Y-%m")
    assert all(month > current_month for month in scheduled["target_completion_month"])


def test_historical_jobs_within_two_year_window():
    df = job_ledger_pipeline.generate(_sample_contractors())
    completed = df[df["job_status"] == "COMPLETED"]["target_completion_month"]
    assert completed.min() >= config.HISTORY_START_DATE.strftime("%Y-%m")
    assert completed.max() <= config.HISTORY_END_DATE.strftime("%Y-%m")


def test_job_ids_are_unique():
    df = job_ledger_pipeline.generate(_sample_contractors())
    assert df["job_id"].is_unique


def test_scheduled_booking_dates_precede_target_month():
    df = job_ledger_pipeline.generate(_sample_contractors())
    scheduled = df[df["job_status"] == "SCHEDULED"]
    for _, row in scheduled.iterrows():
        target_month_start = date.fromisoformat(row["target_completion_month"] + "-01")
        assert row["booking_date"] < target_month_start


def test_schema_columns_present():
    df = job_ledger_pipeline.generate(_sample_contractors())
    expected_cols = {field.name for field in job_ledger_pipeline.SCHEMA}
    assert expected_cols.issubset(set(df.columns))
