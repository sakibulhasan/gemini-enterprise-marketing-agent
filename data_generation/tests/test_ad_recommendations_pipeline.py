"""Tests for ad_recommendations_pipeline — recommendation docs and target months."""

from datetime import date

from dateutil.relativedelta import relativedelta

import ad_recommendations_pipeline as ads


def _expected_target_months() -> list[str]:
    first_of_month = date.today().replace(day=1)
    return [
        (first_of_month + relativedelta(months=i)).strftime("%Y-%m")
        for i in range(2)
    ]


def test_target_months_are_current_and_next():
    assert ads._target_months() == _expected_target_months()


def test_build_recommendation_core_fields():
    rec = ads.build_recommendation("CONT_HVAC_01", "HVAC", "2026-07")
    assert rec["contractor_id"] == "CONT_HVAC_01"
    assert rec["service_category"] == "HVAC"
    assert rec["target_month"] == "2026-07"
    assert rec["recommendation_id"] == "rec_202607_CONT_HVAC_01"
    assert rec["recommendation_type"] == "BUDGET_RAISE"
    assert rec["status"] == "PENDING_REVIEW"


def test_recommendation_id_tracks_target_month():
    rec = ads.build_recommendation("CONT_ROOFING_02", "Roofing", "2026-08")
    assert rec["recommendation_id"] == "rec_202608_CONT_ROOFING_02"
    assert rec["target_month"] == "2026-08"


def test_metrics_impact_shape():
    rec = ads.build_recommendation("CONT_PLUMBING_03", "Plumbing", "2026-07")
    assert set(rec["metrics_impact"]) == {
        "estimated_additional_clicks",
        "estimated_additional_cost",
        "historical_conversion_rate",
        "projected_new_leads",
    }
