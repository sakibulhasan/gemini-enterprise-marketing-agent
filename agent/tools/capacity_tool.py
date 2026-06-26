"""BigQuery connector for FleetSync capacity / profile data (Source 2).

This module contains three functions the Cadence agent calls as tools:

    get_contractor_profile(contractor_id)
        → static profile (name, trade, lat/lon, timezone) from the
          contractors table.  Used to obtain coordinates for the weather tool.

    get_contractor_capacity(contractor_id)
        → monthly capacity snapshot: how many jobs are committed this month
          vs. the contractor's monthly capacity, plus a 6-month trend and a
          3-month forecast window.

    get_all_capacity_signals()
        → one-row-per-contractor summary from the v_capacity_signals view.
          Used by the review-queue tool to quickly assess all contractors at
          once before drilling into individual recommendations.

Monthly capacity rule
---------------------
    monthly_capacity = num_technicians × 10   (10 jobs per technician per month)
    utilization_pct  = committed_jobs / monthly_capacity

    HAS_CAPACITY    (<  70 %) → APPROVE_INCREASE
    TIGHT_CAPACITY  (70–99 %) → PARTIAL_INCREASE
    NO_CAPACITY     (≥ 100 %) → HOLD

Env vars used (see .env.example):
    GOOGLE_CLOUD_PROJECT, BQ_DATASET, BQ_LOCATION
"""

from __future__ import annotations

import os
from typing import Any

# Read runtime config from environment (set in .env or exported shell vars).
_PROJECT  = os.environ.get("GOOGLE_CLOUD_PROJECT")
_DATASET  = os.environ.get("BQ_DATASET", "fleetsync")
_LOCATION = os.environ.get("BQ_LOCATION", "US")


def _client():
    """Return a BigQuery client.  Imported lazily so the module can be loaded
    in offline / unit-test mode without the GCP library installed.
    """
    from google.cloud import bigquery
    return bigquery.Client(project=_PROJECT, location=_LOCATION)


def _rows_to_dicts(row_iter) -> list[dict[str, Any]]:
    """Convert a BigQuery RowIterator to a plain list of dicts.

    DATE and DATETIME values are converted to ISO-format strings so the
    result is directly JSON-serialisable and the agent can read it easily.
    """
    out: list[dict[str, Any]] = []
    for row in row_iter:
        d = dict(row.items())
        # Make any date / datetime values JSON-safe.
        for k, v in d.items():
            if hasattr(v, "isoformat"):   # covers date, datetime, Decimal, etc.
                d[k] = v.isoformat()
        out.append(d)
    return out


def get_contractor_profile(contractor_id: str) -> dict[str, Any]:
    """Return the static profile for a contractor from the contractors table.

    The agent uses latitude / longitude / trade from this result to call the
    weather tool and determine which seasonal demand factors apply.

    Args:
        contractor_id: Canonical contractor id (e.g. "C003").

    Returns:
        Dict with contractor fields, or {"error": ...} if not found.
    """
    from google.cloud import bigquery

    # Parameterised query prevents SQL injection even though ids are internal.
    sql = f"""
        SELECT
            contractor_id, business_name, trade,
            city, state, latitude, longitude, timezone,
            num_technicians, fleetsync_account_id, google_ads_customer_id
        FROM `{_PROJECT}.{_DATASET}.contractors`
        WHERE contractor_id = @cid
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("cid", "STRING", contractor_id)
        ]
    )
    rows = _rows_to_dicts(_client().query(sql, job_config=job_config).result())

    if not rows:
        return {"error": f"no profile found for contractor_id={contractor_id}"}
    return rows[0]


def get_contractor_capacity(contractor_id: str) -> dict[str, Any]:
    """Return the monthly capacity snapshot for a single contractor.

    Pulls two datasets and combines them:

    1. Current-month summary from v_capacity_signals (committed jobs,
       capacity, utilization_pct, available_slots, verdict, forecast window).
    2. 6-month trend from the jobs table directly (month-by-month committed
       job count + revenue so the agent can see the seasonal pattern).

    Args:
        contractor_id: Canonical contractor id (e.g. "C003").

    Returns:
        Dict with:
            current_month : snapshot of this month's capacity signals.
            monthly_trend : list of last 6 historical months (desc order).
        or {"error": ...} if no data is found.
    """
    from google.cloud import bigquery

    # Reusable query parameter for the contractor id.
    cid_param = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("cid", "STRING", contractor_id)
        ]
    )

    # ── Query 1: current-month signals from the view ─────────────────────────
    # The view pre-computes utilization_pct, available_slots, verdict, etc.
    # so we don't need to repeat that logic here.
    view_sql = f"""
        SELECT
            contractor_id, business_name, trade,
            num_technicians, monthly_capacity,
            current_year_month, current_month_jobs,
            current_utilization_pct, available_slots,
            current_month_revenue_usd,
            avg_6m_jobs_per_month, avg_6m_utilization_pct,
            total_next_3m_jobs, avg_next_3m_jobs_per_month,
            avg_next_3m_utilization_pct,
            capacity_verdict, suggested_action
        FROM `{_PROJECT}.{_DATASET}.v_capacity_signals`
        WHERE contractor_id = @cid
    """
    signal_rows = _rows_to_dicts(
        _client().query(view_sql, job_config=cid_param).result()
    )
    if not signal_rows:
        return {"error": f"no capacity data found for contractor_id={contractor_id}"}

    # ── Query 2: 6-month month-by-month trend from the jobs table ────────────
    # Shows the seasonal pattern: is this month unusually busy or quiet?
    trend_sql = f"""
        SELECT
            year_month,
            COUNT(*)                           AS committed_jobs,
            ROUND(SUM(estimated_value_usd), 2) AS revenue_usd
        FROM `{_PROJECT}.{_DATASET}.jobs`
        WHERE contractor_id = @cid
          AND record_type = 'historical'  -- only look at completed/current months
        GROUP BY year_month
        ORDER BY year_month DESC
        LIMIT 6  -- last 6 months is enough context for trend analysis
    """
    trend_rows = _rows_to_dicts(
        _client().query(trend_sql, job_config=cid_param).result()
    )

    return {
        "contractor_id": contractor_id,
        "current_month":  signal_rows[0],   # full capacity snapshot
        "monthly_trend":  trend_rows,        # month-by-month job count trend
    }


def get_all_capacity_signals() -> dict[str, Any]:
    """Return the current-month capacity summary for ALL contractors.

    Backed by the v_capacity_signals view.  Used by the review-queue tool so
    the agent can see every contractor's verdict in a single call before
    deciding which ones need detailed analysis.

    Returns:
        Dict with 'count' (number of contractors) and 'items' (list of rows).
    """
    # Select the columns the agent needs for a fleet-wide overview.
    # Excludes verbose fields like city/state that are not needed at this level.
    sql = f"""
        SELECT
            contractor_id, business_name, trade,
            num_technicians, monthly_capacity,
            current_year_month, current_month_jobs,
            current_utilization_pct, available_slots,
            avg_6m_utilization_pct,
            avg_next_3m_utilization_pct,
            capacity_verdict, suggested_action
        FROM `{_PROJECT}.{_DATASET}.v_capacity_signals`
        ORDER BY current_utilization_pct DESC  -- most-booked contractors first
    """
    rows = _rows_to_dicts(_client().query(sql).result())
    return {"count": len(rows), "items": rows}

