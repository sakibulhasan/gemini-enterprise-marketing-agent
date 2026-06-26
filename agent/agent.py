"""Cadence root agent (Google ADK).

This defines the agent that Gemini Enterprise will register. It wires three data
sources into tools the model can call — each via a DIFFERENT connector:

* Source 1 (Google Ads recommendations)  -> Cloud Storage connector
    get_budget_recommendations, list_open_recommendations
* Source 2 (FleetSync capacity / profile) -> BigQuery connector
    get_contractor_profile, get_contractor_capacity
* Source 3 (live weather)                 -> REST API connector
    get_weather_forecast

Run locally for a quick smoke test:
    adk run agent            # interactive CLI (from repo root)
    adk web                  # local web UI

Then deploy with: python -m agent.deploy
"""

from __future__ import annotations

import os

from google.adk.agents import Agent

from agent.prompts import SYSTEM_INSTRUCTION
from agent.tools.capacity_tool import (
    get_contractor_capacity,
    get_contractor_profile,
)
from agent.tools.gcs_recommendations_tool import (
    get_budget_recommendations,
    list_open_recommendations,
)
from agent.tools.weather_tool import get_weather_forecast

MODEL = os.environ.get("CADENCE_MODEL", "gemini-2.5-flash")

root_agent = Agent(
    name="cadence_budget_capacity_agent",
    model=MODEL,
    description=(
        "Recommends Google Ads budget changes for home-services contractors only "
        "when capacity and weather show the leads can actually be serviced."
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        get_contractor_profile,
        get_budget_recommendations,
        get_contractor_capacity,
        get_weather_forecast,
        list_open_recommendations,
    ],
)
