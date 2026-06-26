"""Tests for contractors_pipeline.generate() — the contractor roster."""

import re

import config
import contractors_pipeline


def test_generates_three_contractors_per_category():
    df = contractors_pipeline.generate()
    assert len(df) == len(config.SERVICE_CATEGORIES) * 3  # 12 contractors
    counts = df["service_category"].value_counts()
    for category in config.SERVICE_CATEGORIES:
        assert counts[category] == 3


def test_capacity_equals_technicians_times_rate():
    df = contractors_pipeline.generate()
    expected = df["num_technicians"] * df["jobs_per_tech_month"]
    assert (df["max_monthly_capacity"] == expected).all()


def test_jobs_per_tech_month_is_constant():
    df = contractors_pipeline.generate()
    assert (df["jobs_per_tech_month"] == contractors_pipeline.JOBS_PER_TECH_MONTH).all()


def test_technician_count_within_expected_range():
    df = contractors_pipeline.generate()
    assert df["num_technicians"].between(2, 5).all()


def test_schema_columns_present():
    df = contractors_pipeline.generate()
    expected_cols = {field.name for field in contractors_pipeline.SCHEMA}
    assert expected_cols.issubset(set(df.columns))


def test_contractor_ids_unique_and_formatted():
    df = contractors_pipeline.generate()
    assert df["contractor_id"].is_unique
    assert df["contractor_id"].apply(lambda x: bool(re.match(r"^CONT_[A-Z]+_\d{2}$", x))).all()
