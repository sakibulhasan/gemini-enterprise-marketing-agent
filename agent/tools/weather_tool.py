"""Live weather tool (Source 3) backed by the free Open-Meteo API.

This is the REST-API connector in the demo. Open-Meteo requires no API key and is
free for non-commercial use, which makes it ideal for the pilot. The tool answers
the analyst question "Is demand about to
spike/drop?" by turning a forecast into a simple, trade-aware demand signal:

* Roofing / Plumbing  -> storms, heavy rain, high wind  => demand SPIKE
* HVAC                 -> heat waves / cold snaps         => demand SPIKE
* Electrical           -> storms (outages)                => demand SPIKE

Returned dicts are JSON-serializable so they can be used directly as ADK
FunctionTool results.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests

OPEN_METEO_URL = os.environ.get("WEATHER_API_BASE", "https://api.open-meteo.com/v1/forecast")
REQUEST_TIMEOUT_SECONDS = 15

# WMO weather codes that indicate disruptive weather (rain/storm/snow).
# https://open-meteo.com/en/docs (Weather variable documentation)
SEVERE_WMO_CODES = {
    65, 67,            # heavy rain / freezing rain
    75, 77,            # heavy snow / snow grains
    82,                # violent rain showers
    86,                # heavy snow showers
    95, 96, 99,        # thunderstorm (+ hail)
}


def get_weather_forecast(
    latitude: float,
    longitude: float,
    trade: str = "",
    forecast_days: int = 3,
) -> dict[str, Any]:
    """Fetch a short-range forecast and derive a trade-aware demand signal.

    Args:
        latitude: Contractor latitude (from the FleetSync ``contractors`` table).
        longitude: Contractor longitude.
        trade: One of HVAC | Plumbing | Electrical | Roofing. Used to interpret
            the forecast into a demand signal. Optional.
        forecast_days: Number of days to forecast (1-7).

    Returns:
        A dict with the raw daily forecast plus a derived ``demand_signal``
        ("SPIKE", "ELEVATED", or "NORMAL") and a human-readable ``rationale``.
        On failure, returns ``{"error": ...}`` instead of raising so the agent
        can degrade gracefully.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_sum,wind_speed_10m_max",
        "timezone": "auto",
        "forecast_days": max(1, min(int(forecast_days), 7)),
    }

    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": f"weather lookup failed: {exc}"}

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    codes = daily.get("weather_code", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    wind = daily.get("wind_speed_10m_max", [])

    days: list[dict[str, Any]] = []
    for i, day in enumerate(dates):
        days.append({
            "date": day,
            "weather_code": _safe(codes, i),
            "temp_max_c": _safe(tmax, i),
            "temp_min_c": _safe(tmin, i),
            "precipitation_mm": _safe(precip, i),
            "wind_speed_max_kmh": _safe(wind, i),
        })

    signal, rationale = _demand_signal(trade, days)

    return {
        "latitude": latitude,
        "longitude": longitude,
        "trade": trade,
        "retrieved_at": datetime.utcnow().isoformat() + "Z",
        "forecast": days,
        "demand_signal": signal,
        "rationale": rationale,
    }


def _safe(seq: list, idx: int) -> Any:
    return seq[idx] if idx < len(seq) else None


def _demand_signal(trade: str, days: list[dict[str, Any]]) -> tuple[str, str]:
    """Translate the forecast into a trade-aware demand signal + rationale."""
    trade_norm = (trade or "").strip().lower()

    severe_days = [d for d in days if d["weather_code"] in SEVERE_WMO_CODES]
    heavy_rain_days = [d for d in days if (d["precipitation_mm"] or 0) >= 15]
    high_wind_days = [d for d in days if (d["wind_speed_max_kmh"] or 0) >= 45]
    hot_days = [d for d in days if (d["temp_max_c"] or -999) >= 35]
    cold_days = [d for d in days if (d["temp_min_c"] or 999) <= -5]

    reasons: list[str] = []
    spike = False

    if trade_norm in ("roofing", "plumbing"):
        if severe_days or heavy_rain_days or high_wind_days:
            spike = True
            reasons.append("storm/heavy-rain/high-wind in the forecast drives roof & water-intrusion calls")
    if trade_norm == "hvac":
        if hot_days:
            spike = True
            reasons.append("heat wave in the forecast drives AC repair demand")
        if cold_days:
            spike = True
            reasons.append("cold snap in the forecast drives heating demand")
    if trade_norm == "electrical":
        if severe_days or high_wind_days:
            spike = True
            reasons.append("storms/high wind raise outage-related electrical demand")

    # Generic fallback when trade is unknown or no trade-specific trigger fired.
    if not spike and (severe_days or heavy_rain_days):
        return "ELEVATED", "Disruptive weather in the forecast may modestly raise demand."

    if spike:
        return "SPIKE", "; ".join(reasons)

    return "NORMAL", "No significant weather-driven demand change expected."
