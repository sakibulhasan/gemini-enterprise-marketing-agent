"""Shared, deterministic fleet of home-services contractors.

Both synthetic data generators (Google Ads export -> GCS, and FleetSync capacity
-> BigQuery) import this module so the two data sources line up on the same
``contractor_id`` values. That join key is what lets the Cadence agent combine
"what Google is suggesting" with "can this contractor actually handle more
leads".

Coordinates are real city centroids so the live weather API returns sensible
forecasts for each contractor.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List


@dataclass(frozen=True)
class Contractor:
    contractor_id: str          # canonical join key across all sources
    business_name: str
    trade: str                  # HVAC | Plumbing | Electrical | Roofing
    city: str
    state: str
    latitude: float
    longitude: float
    timezone: str
    num_technicians: int
    # Simulation seed: the fraction of daily capacity booked on a typical
    # mid-season weekday without weather events.  Used only by the data
    # generator to produce realistic variation across contractors.
    # The agent never sees this value — it reads avg_90d_booked_pct from
    # the v_capacity_signals view instead.
    sim_base_util: float
    # Current Google Ads daily budget (USD) — used by the ads data generator.
    current_daily_budget_usd: float
    # FleetSync account identifier (mirrors how a dispatch system keys a customer)
    fleetsync_account_id: str
    # Google Ads external customer id (10 digits, like real Ads accounts)
    google_ads_customer_id: str

    def as_dict(self) -> dict:
        return asdict(self)


# A small but representative fleet. Weather-sensitive trades (Roofing, Plumbing)
# are included so the storm-demand signal in the use case is demonstrable.
CONTRACTORS: List[Contractor] = [
    Contractor(
        contractor_id="C001",
        business_name="Polar Bear HVAC",
        trade="HVAC",
        city="Phoenix",
        state="AZ",
        latitude=33.4484,
        longitude=-112.0740,
        timezone="America/Phoenix",
        num_technicians=10,
        sim_base_util=0.55,
        current_daily_budget_usd=250.0,
        fleetsync_account_id="FS-1001",
        google_ads_customer_id="4830010001",
    ),
    Contractor(
        contractor_id="C002",
        business_name="RapidFlow Plumbing",
        trade="Plumbing",
        city="Houston",
        state="TX",
        latitude=29.7604,
        longitude=-95.3698,
        timezone="America/Chicago",
        num_technicians=8,
        sim_base_util=0.65,
        current_daily_budget_usd=100.0,
        fleetsync_account_id="FS-1002",
        google_ads_customer_id="4830010002",
    ),
    Contractor(
        contractor_id="C003",
        business_name="Summit Roofing Co",
        trade="Roofing",
        city="Denver",
        state="CO",
        latitude=39.7392,
        longitude=-104.9903,
        timezone="America/Denver",
        num_technicians=6,
        sim_base_util=0.80,
        current_daily_budget_usd=200.0,
        fleetsync_account_id="FS-1003",
        google_ads_customer_id="4830010003",
    ),
    Contractor(
        contractor_id="C004",
        business_name="BrightSpark Electric",
        trade="Electrical",
        city="Atlanta",
        state="GA",
        latitude=33.7490,
        longitude=-84.3880,
        timezone="America/New_York",
        num_technicians=10,
        sim_base_util=0.60,
        current_daily_budget_usd=150.0,
        fleetsync_account_id="FS-1004",
        google_ads_customer_id="4830010004",
    ),
    Contractor(
        contractor_id="C005",
        business_name="Coastline Roofing",
        trade="Roofing",
        city="Tampa",
        state="FL",
        latitude=27.9506,
        longitude=-82.4572,
        timezone="America/New_York",
        num_technicians=5,
        sim_base_util=0.75,
        current_daily_budget_usd=150.0,
        fleetsync_account_id="FS-1005",
        google_ads_customer_id="4830010005",
    ),
    Contractor(
        contractor_id="C006",
        business_name="Cascade Plumbing & Heating",
        trade="Plumbing",
        city="Seattle",
        state="WA",
        latitude=47.6062,
        longitude=-122.3321,
        timezone="America/Los_Angeles",
        num_technicians=9,
        sim_base_util=0.62,
        current_daily_budget_usd=75.0,
        fleetsync_account_id="FS-1006",
        google_ads_customer_id="4830010006",
    ),
    Contractor(
        contractor_id="C007",
        business_name="Desert Air Mechanical",
        trade="HVAC",
        city="Las Vegas",
        state="NV",
        latitude=36.1699,
        longitude=-115.1398,
        timezone="America/Los_Angeles",
        num_technicians=8,
        sim_base_util=0.67,
        current_daily_budget_usd=200.0,
        fleetsync_account_id="FS-1007",
        google_ads_customer_id="4830010007",
    ),
    Contractor(
        contractor_id="C008",
        business_name="Liberty Electric Services",
        trade="Electrical",
        city="Chicago",
        state="IL",
        latitude=41.8781,
        longitude=-87.6298,
        timezone="America/Chicago",
        num_technicians=9,
        sim_base_util=0.68,
        current_daily_budget_usd=150.0,
        fleetsync_account_id="FS-1008",
        google_ads_customer_id="4830010008",
    ),
]


def get_contractor(contractor_id: str) -> Contractor | None:
    """Return the contractor with the given id, or ``None`` if not found."""
    for c in CONTRACTORS:
        if c.contractor_id == contractor_id:
            return c
    return None
