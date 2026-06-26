"""Cloud Storage connector for Google Ads budget recommendations (Source 1).

This is the GCS half of the multi-connector demo. Instead of registering the GCS
export as a BigQuery external table, the agent reads the newline-delimited JSON
(JSONL) objects **directly from Cloud Storage** with the
``google-cloud-storage`` client. This keeps Source 1 fully decoupled from
BigQuery and shows a second, distinct connector working alongside it.

Layout the generator writes:
    gs://${GCS_BUCKET}/${GCS_ADS_PREFIX}/dt=YYYY-MM-DD/google_ads_recommendations_*.jsonl

Env vars used (see .env.example):
    GCS_BUCKET, GCS_ADS_PREFIX
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable

_BUCKET = os.environ.get("GCS_BUCKET")
_PREFIX = os.environ.get("GCS_ADS_PREFIX", "google_ads_export")


def _storage_client():
    # Lazy import so local/offline use without GCP libs doesn't break import.
    from google.cloud import storage

    return storage.Client()


def _iter_recommendation_rows(prefix: str | None = None) -> Iterable[dict[str, Any]]:
    """Stream every recommendation row from the JSONL objects under the prefix."""
    if not _BUCKET:
        raise RuntimeError("GCS_BUCKET env var is not set. See .env.example.")

    client = _storage_client()
    list_prefix = prefix if prefix is not None else f"{_PREFIX}/"
    for blob in client.list_blobs(_BUCKET, prefix=list_prefix):
        if not blob.name.endswith(".jsonl"):
            continue
        text = blob.download_as_text()
        for line in text.splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)


def _latest_per_campaign(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the newest row per (contractor_id, campaign_id)."""
    latest: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = (row.get("contractor_id"), row.get("campaign_id"))
        existing = latest.get(key)
        if existing is None or str(row.get("export_date", "")) > str(existing.get("export_date", "")):
            latest[key] = row
    return list(latest.values())


def get_budget_recommendations(contractor_id: str) -> dict[str, Any]:
    """Return the latest Google Ads budget recommendation(s) for a contractor.

    Reads the JSONL export directly from Cloud Storage (no BigQuery involved) and
    answers "What is Google suggesting, and what's the spend?".

    Args:
        contractor_id: Canonical contractor id (e.g. "C003").

    Returns:
        Dict with a list of recommendations (latest per campaign, sorted by the
        size of the suggested increase), or ``{"error": ...}`` if none found.
    """
    try:
        all_rows = [r for r in _iter_recommendation_rows() if r.get("contractor_id") == contractor_id]
    except Exception as exc:  # surface connector/auth errors to the agent cleanly
        return {"error": f"Cloud Storage read failed: {exc}"}

    if not all_rows:
        return {"error": f"no Google Ads recommendations in GCS for contractor_id={contractor_id}"}

    recs = _latest_per_campaign(all_rows)
    recs.sort(key=lambda r: r.get("recommended_budget_increase_usd", 0), reverse=True)

    keep = (
        "contractor_id", "account_name", "campaign_id", "campaign_name",
        "export_date", "current_daily_budget_usd", "recommended_daily_budget_usd",
        "recommended_budget_increase_usd", "lost_impression_share_budget",
        "estimated_incremental_clicks", "estimated_incremental_conversions",
    )
    trimmed = [{k: r.get(k) for k in keep} for r in recs]
    return {"contractor_id": contractor_id, "source": "cloud_storage", "recommendations": trimmed}


def list_open_recommendations(limit: int = 20) -> dict[str, Any]:
    """List contractors that currently have a Google Ads budget recommendation.

    This is the analyst review queue ("what needs a decision today?"). It reads
    recommendations from Cloud Storage and merges in the capacity verdict from
    BigQuery (``v_capacity_signals``) - i.e. a cross-connector join done in the
    application layer rather than in SQL.

    Args:
        limit: Maximum number of rows to return.
    """
    try:
        rows = list(_iter_recommendation_rows())
    except Exception as exc:
        return {"error": f"Cloud Storage read failed: {exc}"}

    recs = _latest_per_campaign(rows)

    # Enrich with capacity verdict from the BigQuery connector (best-effort).
    verdicts = _capacity_verdicts_by_contractor()

    items = []
    for r in recs:
        cid = r.get("contractor_id")
        v = verdicts.get(cid, {})
        items.append({
            "contractor_id": cid,
            "business_name": r.get("account_name"),
            "campaign_name": r.get("campaign_name"),
            "recommendation_date": r.get("export_date"),
            "current_daily_budget_usd": r.get("current_daily_budget_usd"),
            "recommended_budget_increase_usd": r.get("recommended_budget_increase_usd"),
            "booked_pct": v.get("booked_pct"),
            "capacity_verdict": v.get("capacity_verdict"),
            "suggested_action": v.get("suggested_action"),
        })

    items.sort(key=lambda x: x.get("recommended_budget_increase_usd") or 0, reverse=True)
    items = items[: int(limit)]
    return {"count": len(items), "items": items}


def _capacity_verdicts_by_contractor() -> dict[str, dict[str, Any]]:
    """Pull the per-contractor capacity verdict from BigQuery; empty on failure."""
    try:
        from agent.tools.capacity_tool import get_all_capacity_signals

        result = get_all_capacity_signals()
        return {row["contractor_id"]: row for row in result.get("items", [])}
    except Exception:
        return {}
