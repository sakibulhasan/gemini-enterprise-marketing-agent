"""Deploy the Cadence agent to Vertex AI Agent Engine.

Agent Engine is the managed runtime that Gemini Enterprise calls when you
register a custom agent. This script packages ``root_agent`` and deploys it.

After it prints the Agent Engine *resource name*, you register that resource in
the Gemini Enterprise console (see README, step 6).

Prerequisites (env vars, see .env.example):
    GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, AGENT_ENGINE_STAGING_BUCKET
    GCS_BUCKET, GCS_ADS_PREFIX, BQ_DATASET
    GOOGLE_GENAI_USE_VERTEXAI=TRUE
    Application Default Credentials:  `gcloud auth application-default login`

Usage:
    python -m agent.deploy            # create / update the deployment
    python -m agent.deploy --list     # list existing deployments
"""

from __future__ import annotations

import argparse
import os

import vertexai
from vertexai import agent_engines
from vertexai.preview import reasoning_engines

from agent.agent import root_agent

# Runtime dependencies the deployed agent needs in the cloud.
REQUIREMENTS = [
    "google-adk>=1.0.0",
    "google-cloud-aiplatform[adk,agent_engines]>=1.95.0",
    "google-cloud-bigquery>=3.25.0",
    "google-cloud-storage>=2.18.0",
    "requests>=2.32.0",
]


def _init() -> tuple[str, str]:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    staging_bucket = os.environ["AGENT_ENGINE_STAGING_BUCKET"]
    vertexai.init(project=project, location=location, staging_bucket=staging_bucket)
    return project, location


def deploy() -> None:
    project, location = _init()
    display_name = os.environ.get("AGENT_DISPLAY_NAME", "Cadence Budget Capacity Agent")

    # Environment variables baked into the deployed runtime so the BigQuery,
    # Cloud Storage and weather tools resolve the right project/dataset/bucket/API.
    env_vars = {
        "GOOGLE_CLOUD_PROJECT": project,
        "GOOGLE_CLOUD_LOCATION": location,
        "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
        "BQ_DATASET": os.environ.get("BQ_DATASET", "fleetsync"),
        "BQ_LOCATION": os.environ.get("BQ_LOCATION", "US"),
        "GCS_BUCKET": os.environ["GCS_BUCKET"],
        "GCS_ADS_PREFIX": os.environ.get("GCS_ADS_PREFIX", "google_ads_export"),
        "WEATHER_API_BASE": os.environ.get(
            "WEATHER_API_BASE", "https://api.open-meteo.com/v1/forecast"
        ),
        "CADENCE_MODEL": os.environ.get("CADENCE_MODEL", "gemini-2.5-flash"),
    }

    app = reasoning_engines.AdkApp(agent=root_agent, enable_tracing=True)

    print(f"Deploying '{display_name}' to Agent Engine in {project}/{location} ...")
    remote_app = agent_engines.create(
        agent_engine=app,
        display_name=display_name,
        requirements=REQUIREMENTS,
        extra_packages=["agent", "config"],
        env_vars=env_vars,
    )
    print("\nDeployment complete.")
    print(f"Agent Engine resource name:\n  {remote_app.resource_name}")
    print(
        "\nNext: register this resource in Gemini Enterprise "
        "(README step 6) so analysts can chat with Cadence."
    )


def list_deployments() -> None:
    _init()
    for app in agent_engines.list():
        print(f"{app.display_name}\t{app.resource_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy/list the Cadence agent on Agent Engine.")
    parser.add_argument("--list", action="store_true", help="List existing deployments and exit.")
    args = parser.parse_args()
    if args.list:
        list_deployments()
    else:
        deploy()


if __name__ == "__main__":
    main()
