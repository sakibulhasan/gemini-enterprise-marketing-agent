# Cadence — Gemini Enterprise Marketing Agent

> All organization, product, and system names in this repo (**Northwind Digital**,
> **Cadence**, **FleetSync**) are synthetic placeholders. All data is synthetic.

---

## The Problem

Northwind Digital manages Google Ads for home-services contractors (HVAC,
plumbing, electrical, roofing). Every day, Google surfaces recommendations like:

> *"Increase your Storm Damage Repair campaign budget from $200/day to $270/day —
> you're losing 28% of impressions to budget."*

The natural reaction is to approve: more spend = more leads = more revenue.
**The catch:** if a contractor's technicians are already fully booked, those
extra leads are wasted money. The contractor physically cannot service them.
Before approving, an analyst must check the dispatch system — and doing that
manually for dozens of accounts every day doesn't scale.

---

## The Solution

Cadence automates the capacity check by connecting three data sources and
combining them into a single, defensible recommendation for a human analyst to
approve or decline.

| # | Source | Question it answers | Connector |
|---|--------|---------------------|-----------|
| 1 | Google Ads + Recommendations | "What is Google suggesting, and what's the spend?" | **Cloud Storage** (JSONL, direct read) |
| 2 | FleetSync (capacity/dispatch) | "Can this contractor actually handle more leads?" | **BigQuery** |
| 3 | Weather | "Is demand about to spike or drop?" | **REST API** (live Open-Meteo) |

The answer to question 2 is the **key differentiator**. Sources 1 and 3 tell you
about *opportunity*. Source 2 tells you whether that opportunity can be
fulfilled.

---

## How It Works — Mock Data Walkthrough

The following traces three contractors through every step using the exact
numbers the generators produce. All values are deterministic: they come from
the fixed code constants in `generate_jobs_data.py` and `generate_google_ads_data.py`.

### The three contractors in this walkthrough

| contractor_id | Business name | Trade | Technicians | Daily budget (Google Ads) |
|---|---|---|---|---|
| C001 | Polar Bear HVAC | HVAC | 10 | $250/day |
| C003 | Summit Roofing Co | Roofing | 6 | $200/day |
| C005 | Coastline Roofing | Roofing | 5 | $150/day |

> The per-contractor simulation seed (`sim_base_util`) lives in `config/contractors.py`
> and is only used by the generator. The agent never reads it — it uses
> `avg_6m_utilization_pct` computed from real historical rows in the BigQuery view.

---

### Source 1 — Google Ads recommendations (Cloud Storage)

The generator applies three code constants to every contractor's budget:

```
recommended_daily  = current_daily × (1 + BUDGET_BUMP_PCT)       BUDGET_BUMP_PCT  = 0.35
budget_increase    = recommended_daily − current_daily
incremental_clicks = round(budget_increase × CLICKS_PER_DOLLAR)   CLICKS_PER_DOLLAR = 1.2
conversions        = incremental_clicks × CONVERSION_RATE          CONVERSION_RATE  = 0.10
```

**C001 — Polar Bear HVAC ($250/day)**

```
recommended_daily  = 250 × (1 + 0.35) = 250 × 1.35 = $337.50
budget_increase    = 337.50 − 250.00  = $87.50
incremental_clicks = round(87.50 × 1.2) = 105 clicks
conversions        = 105 × 0.10 = 10.5
```

**C003 — Summit Roofing Co ($200/day)**

```
recommended_daily  = 200 × 1.35 = $270.00
budget_increase    = $70.00
incremental_clicks = round(70 × 1.2) = 84 clicks
conversions        = 84 × 0.10 = 8.4
```

**C005 — Coastline Roofing ($150/day)**

```
recommended_daily  = 150 × 1.35 = $202.50
budget_increase    = $52.50
incremental_clicks = round(52.50 × 1.2) = 63 clicks
conversions        = 63 × 0.10 = 6.3
```

**What lands in `gs://…/google_ads_export/dt=2026-06-20/` (one JSONL line per campaign):**

```jsonl
{"contractor_id":"C001","campaign_name":"AC Repair - Search","current_daily_budget_usd":250.0,"recommended_daily_budget_usd":337.5,"recommended_budget_increase_usd":87.5,"lost_impression_share_budget":0.28,"estimated_incremental_clicks":105,"estimated_incremental_conversions":10.5}
{"contractor_id":"C003","campaign_name":"Storm Damage Repair - Search","current_daily_budget_usd":200.0,"recommended_daily_budget_usd":270.0,"recommended_budget_increase_usd":70.0,"lost_impression_share_budget":0.28,"estimated_incremental_clicks":84,"estimated_incremental_conversions":8.4}
{"contractor_id":"C005","campaign_name":"Roof Replacement - Search","current_daily_budget_usd":150.0,"recommended_daily_budget_usd":202.5,"recommended_budget_increase_usd":52.5,"lost_impression_share_budget":0.28,"estimated_incremental_clicks":63,"estimated_incremental_conversions":6.3}
```

At this point the analyst only knows what Google is asking. They have no idea
whether any of these contractors can actually service the extra leads.

---

### Source 2 — FleetSync jobs (BigQuery)

Capacity is modelled **monthly**: each technician handles 10 jobs per calendar
month.  For each (contractor, month) pair the generator calculates:

```
monthly_capacity = num_technicians × JOBS_PER_TECH_PER_MONTH      JOBS_PER_TECH_PER_MONTH = 10
seasonal_factor  = MONTHLY_FACTORS[trade][month]                  (code constant, see below)
effective_util   = sim_base_util × seasonal_factor               ← sim_base_util set per-contractor
                                                                    in config/contractors.py; never
                                                                    exposed to the agent
                 × FUTURE_BOOKING_RATE   for forecast months       FUTURE_BOOKING_RATE = 0.70
committed_jobs   = round(monthly_capacity × min(effective_util, 1.05))
available_slots  = max(0, monthly_capacity − committed_jobs)
utilization_pct  = committed_jobs / monthly_capacity
```

Each committed job gets a full client record (name, address, city, phone) and a
specific job type.  Historical jobs carry realistic statuses (completed /
cancelled / in\_progress); forecast jobs are all `scheduled`.

**Seasonal factors (MONTHLY\_FACTORS — code constant in `generate_jobs_data.py`):**

| Trade | Jan | Feb | Mar | Apr | May | **Jun** | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HVAC | 0.70 | 0.72 | 0.80 | 0.88 | 1.00 | **1.20** | 1.30 | 1.25 | 1.00 | 0.82 | 0.88 | 0.95 |
| Plumbing | 1.10 | 1.00 | 0.92 | 0.88 | 0.88 | **0.85** | 0.82 | 0.82 | 0.88 | 0.92 | 1.00 | 1.10 |
| Electrical | 0.90 | 0.90 | 0.92 | 0.95 | 1.00 | **1.05** | 1.10 | 1.08 | 1.00 | 0.95 | 0.95 | 0.92 |
| Roofing | 0.65 | 0.70 | 0.88 | 1.10 | 1.20 | **1.15** | 1.05 | 1.00 | 1.10 | 1.20 | 0.88 | 0.65 |

*The calculations below are for June 2026.*

**C001 — Polar Bear HVAC (10 techs, June)**

```
monthly_capacity = 10 × 10 = 100 jobs
seasonal_factor  = 1.20  (HVAC, June)
effective_util   = 0.55 × 1.20 = 0.660
committed_jobs   = round(100 × 0.660) = 66 jobs
available_slots  = 100 − 66 = 34 open slots
utilization_pct  = 0.660  ← 66% booked: comfortable headroom
```

**C003 — Summit Roofing Co (6 techs, June)**

```
monthly_capacity = 6 × 10 = 60 jobs
seasonal_factor  = 1.15  (Roofing, June — spring/summer roof-repair season)
effective_util   = 0.80 × 1.15 = 0.920
committed_jobs   = round(60 × 0.920) = 55 jobs
available_slots  = 60 − 55 = 5 open slots
utilization_pct  = 0.917  ← 91.7% booked: tight, very little room for new leads
```

**C005 — Coastline Roofing (5 techs, June)**

```
monthly_capacity = 5 × 10 = 50 jobs
seasonal_factor  = 1.15  (Roofing, June)
effective_util   = 0.75 × 1.15 = 0.8625
committed_jobs   = round(50 × 0.8625) = 43 jobs
available_slots  = 50 − 43 = 7 open slots
utilization_pct  = 0.860  ← 86% booked: tight
```

**Sample `fleetsync.jobs` rows for June 2026:**

```
job_id               contractor_id  year_month  trade    job_type            client_name    client_city  status       estimated_value_usd  record_type
C001-2026-06-0000    C001           2026-06     HVAC     Heat Pump Service   Mark White     Phoenix      completed    191.77               historical
C001-2026-06-0001    C001           2026-06     HVAC     AC Tune-Up          Patricia Jones Phoenix      in_progress  340.50               historical
… (66 rows total for C001 in June)
C003-2026-06-0000    C003           2026-06     Roofing  Storm Damage Repair James Smith    Denver       scheduled    4280.00              historical
… (55 rows total for C003 in June)
C005-2026-06-0000    C005           2026-06     Roofing  Shingle Replacement Mary Johnson   Tampa        in_progress  2150.00              historical
… (43 rows total for C005 in June)
```

Forecast rows (next 3 months, `record_type='forecast'`) carry pre-committed
jobs scaled by `FUTURE_BOOKING_RATE = 0.70`.  Example for July 2026:

```
C001: round(100 × 0.55 × 1.30 × 0.70) = 50 forecast jobs  (50% of Jul capacity pre-booked)
C003: round(60  × 0.80 × 1.05 × 0.70) = 35 forecast jobs  (58% of Jul capacity pre-booked)
C005: round(50  × 0.75 × 1.05 × 0.70) = 28 forecast jobs  (56% of Jul capacity pre-booked)
```

---

### Step 4 — The decision layer: `v_capacity_signals` view

Step 4 runs a SQL view that does three things:

1. Aggregates `jobs` rows into **monthly committed job counts** per contractor.
2. Computes the **current month’s utilization** against monthly capacity.
3. Applies **business rules as CASE logic** to derive `capacity_verdict` and `suggested_action`.

```sql
monthly_capacity = num_technicians × 10
utilization_pct  = committed_jobs / monthly_capacity

CASE
  WHEN committed_jobs >= monthly_capacity     →  NO_CAPACITY    / HOLD
  WHEN utilization_pct >= 0.70                →  TIGHT_CAPACITY / PARTIAL_INCREASE
  ELSE                                        →  HAS_CAPACITY   / APPROVE_INCREASE
END
```

The view also exposes `avg_next_3m_utilization_pct` from the forecast rows and
`avg_6m_utilization_pct` from the last 6 completed months.  Together these let
the agent reason about whether current-month tightness is a seasonal pattern or
a one-off.

**View output (`v_capacity_signals`) for June 2026:**

```
contractor_id  business_name      monthly_capacity  current_month_jobs  utilization_pct  available_slots  avg_6m_utilization_pct  avg_next_3m_utilization_pct  capacity_verdict  suggested_action
C001           Polar Bear HVAC    100               66                  0.660            34               ~0.463                  ~0.457                       HAS_CAPACITY      APPROVE_INCREASE
C003           Summit Roofing Co  60                55                  0.917            5                ~0.692                  ~0.589                       TIGHT_CAPACITY    PARTIAL_INCREASE
C005           Coastline Roofing  50                43                  0.860            7                ~0.643                  ~0.554                       TIGHT_CAPACITY    PARTIAL_INCREASE
```

`avg_6m_utilization_pct` is computed from the last 6 completed months of real
historical job rows — it shows whether this month’s utilization level is
typical or unusually high.  C003’s 6-month average is already 69 %, meaning
91 % this month is the seasonal peak, not an anomaly.

---

### Putting it all together — what Cadence tells the analyst

The agent reads Source 1 (GCS) and Source 2 (BigQuery) and cross-references them
by `contractor_id`, then calls Source 3 (weather REST API) to check live demand:

| contractor_id | Source 1 — Google says | Source 2 — FleetSync says | Source 3 — Weather | **Cadence decision** |
|---|---|---|---|---|
| C001 | +$87.50/day | 66/100 jobs this month (66% utilized, 34 open slots) → HAS_CAPACITY | NORMAL | **APPROVE** full +$87.50 |
| C003 | +$70.00/day | 55/60 jobs this month (91.7% utilized, 5 open slots) → TIGHT_CAPACITY | NORMAL | **PARTIAL** — nearly at capacity; cautious increase only |
| C005 | +$52.50/day | 43/50 jobs this month (86% utilized, 7 open slots) → TIGHT_CAPACITY | NORMAL | **PARTIAL** — 85 %+ booked; limited room for more leads |

Without Source 2, an analyst looking only at Source 1 would approve all three.
Cadence correctly blocks C003, preventing wasted spend on leads that cannot be
fulfilled.

---

## Architecture

```
                         ┌─────────────────────────────┐
   Source 1: Google Ads  │  GCS bucket (JSONL export)  │   Cloud Storage
   + Recommendations ───▶│  google_ads_export/dt=.../  │── connector (direct read)
                         └─────────────────────────────┘        │
                                                                 ▼
   Source 2: FleetSync   ┌─────────────────────────────┐   ┌───────────────────────┐
   (monthly jobs)  ──▶│  BigQuery dataset `fleetsync`│──▶│  Cadence agent (ADK)  │
                         │   • contractors              │BQ │   tools:              │
                         │   • jobs                    │con│   • profile  (BQ)     │
                         │   • v_capacity_signals (view)│tor│   • get/list recs     │
                         └─────────────────────────────┘   │     (GCS)             │
                                                            │   • weather  (REST)   │
   Source 3: Weather     ┌─────────────────────────────┐   └───────────┬───────────┘
   (live Open-Meteo) ───▶│  REST API (no key)          │── REST ───────┘
                         └─────────────────────────────┘                 │ deploy
                                                                         ▼
                         ┌─────────────────────────────────────────────┐
                         │  Vertex AI Agent Engine (managed runtime)   │
                         └────────────────┬───────────────────────────┘
                                          │ register
                                          ▼
                         ┌─────────────────────────────────────────────┐
                         │  Gemini Enterprise — analysts chat with      │
                         │  Cadence; approve / decline recommendations  │
                         └─────────────────────────────────────────────┘
```

Join key across all sources: **`contractor_id`** (e.g. `C003`).
Weather joins via the contractor's `latitude` / `longitude` / `trade`.

---

## Repository layout

```
.
├── config/
│   └── contractors.py            # fleet definition: num_technicians, sim_base_util (generator seed), budgets
├── data_generation/
│   ├── generate_google_ads_data.py   # Source 1 → JSONL → Cloud Storage
│   └── generate_jobs_data.py         # Source 2 → monthly jobs CSV → BigQuery (idempotent)
├── bigquery/
│   ├── 01_create_dataset.sql
│   ├── 02_create_tables.sql          # (optional) explicit schema for contractors + jobs
│   └── 03_capacity_view.sql          # v_capacity_signals — monthly decision layer
├── agent/
│   ├── agent.py                      # root_agent (ADK)
│   ├── prompts.py                    # reasoning policy
│   ├── deploy.py                     # deploy to Vertex AI Agent Engine
│   └── tools/
│       ├── gcs_recommendations_tool.py  # Cloud Storage connector
│       ├── capacity_tool.py             # BigQuery connector
│       └── weather_tool.py              # REST connector
├── scripts/
│   ├── setup_gcp.sh                  # provision GCP resources
│   └── run_bigquery_sql.sh           # run the SQL files
├── requirements.txt
└── .env.example
```

---

## Quick-start — Run, Deploy, and Test

### Prerequisites
- GCP project with billing enabled and Gemini Enterprise provisioned
- `gcloud` + `bq` CLI installed, Python 3.10+
- `gcloud auth login && gcloud auth application-default login`

---

### Step 0 — Configure and install

```bash
cp .env.example .env
# Edit .env: set GOOGLE_CLOUD_PROJECT, GCS_BUCKET, AGENT_ENGINE_STAGING_BUCKET

python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

set -a; source .env; set +a
```

> **Tip:** `AGENT_DISPLAY_NAME` must be quoted in `.env` — spaces in unquoted
> values cause `source .env` to fail.

---

### Step 1 — Provision GCP resources

```bash
bash scripts/setup_gcp.sh
```

Creates `GCS_BUCKET`, `AGENT_ENGINE_STAGING_BUCKET`, BigQuery dataset, and
enables `aiplatform`, `bigquery`, `storage`, and `discoveryengine` APIs.

---

### Step 2 — Generate and upload Source 1 (Google Ads → Cloud Storage)

```bash
python -m data_generation.generate_google_ads_data --days 3 --upload

# verify
gcloud storage ls -r "gs://$GCS_BUCKET/$GCS_ADS_PREFIX/**"
```

Produces 16 JSONL records per day (2 campaigns × 8 contractors). The agent reads
these directly from the bucket — no BigQuery external table.

---

### Step 3 — Generate and load Source 2 (FleetSync jobs → BigQuery)

```bash
python -m data_generation.generate_jobs_data --load-bq
# Idempotent: queries BQ first and only loads months that are missing.
# Default window: 24 historical months + current month + 3 forecast months.

# verify
bq query --use_legacy_sql=false \
  "SELECT year_month, COUNT(*) AS jobs FROM \`$GOOGLE_CLOUD_PROJECT.$BQ_DATASET.jobs\` GROUP BY 1 ORDER BY 1 DESC LIMIT 5"
```

Creates `contractors` (8 rows) and `jobs` (~11,000 rows: one row per committed
job across 28 months × 8 contractors).  Re-running the script only adds
months that are missing — no duplicates.

---

### Step 4 — Create the decision layer

```bash
bash scripts/run_bigquery_sql.sh
```

Creates `v_capacity_signals`. The script prints a preview table showing
`capacity_verdict` and `suggested_action` for every contractor.

---

### Step 5 — Test the agent locally

```bash
adk run agent          # CLI chat
# or
adk web                # browser UI at http://localhost:8000
```

Ask: *"Should I increase the budget for C003?"*
Cadence calls all three connectors and returns HOLD / PARTIAL / APPROVE with
specific numbers and a rationale.

---

### Step 6 — Deploy to Vertex AI Agent Engine

```bash
python -m agent.deploy
```

Note the printed resource name — you need it in the next step:
```
projects/123456789/locations/us-central1/reasoningEngines/9876543210
```

---

### Step 7 — Register in Gemini Enterprise

1. Gemini Enterprise console → **Agents → Add agent → Agent Engine / ADK**
2. Paste the resource name from Step 6
3. Set display name and publish

Then grant the Agent Engine service account access to the data:

```bash
PROJECT_NUMBER=$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" \
  --format='value(projectNumber)')
SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

# BigQuery (Source 2)
gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
  --member="serviceAccount:${SA}" --role="roles/bigquery.dataViewer"
gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
  --member="serviceAccount:${SA}" --role="roles/bigquery.jobUser"

# Cloud Storage (Source 1)
gcloud storage buckets add-iam-policy-binding "gs://$GCS_BUCKET" \
  --member="serviceAccount:${SA}" --role="roles/storage.objectViewer"
```

---

### Step 8 — Test in Gemini Enterprise

Open the Gemini Enterprise chat and ask:

> *"Google wants me to bump the budget for Summit Roofing — should I?"*

Cadence retrieves capacity from BigQuery, recommendations from Cloud Storage,
and live weather from Open-Meteo, then responds with HOLD / PARTIAL INCREASE /
APPROVE INCREASE, a specific dollar figure, and a rationale.

---

### (Optional) Step 9 — Add data stores for grounded search

- **BigQuery data store:** point at `fleetsync.v_capacity_signals`
- **Cloud Storage data store:** point at `gs://$GCS_BUCKET/$GCS_ADS_PREFIX/`

Attach both to the same Gemini Enterprise app so analysts can search raw data
alongside chatting with Cadence.

---

## Configuration reference

### Required — set these in `.env` before anything else

| Variable | Example | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `my-cadence-demo` | GCP project ID (not number) |
| `GCS_BUCKET` | `my-cadence-demo-ads-export` | Bucket for Google Ads JSONL export |
| `AGENT_ENGINE_STAGING_BUCKET` | `gs://my-cadence-demo-staging` | Staging bucket for Agent Engine deploy |

### Optional — safe to leave as defaults

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Vertex AI / Agent Engine region |
| `BQ_DATASET` | `fleetsync` | BigQuery dataset name |
| `BQ_LOCATION` | `US` | BigQuery location (match bucket region) |
| `GCS_ADS_PREFIX` | `google_ads_export` | Folder prefix inside the bucket |
| `AGENT_DISPLAY_NAME` | `"Cadence Budget Capacity Agent"` | Label in Gemini Enterprise console |
| `CADENCE_MODEL` | `gemini-2.5-flash` | Gemini model used by the agent |

### Data generation code constants

All generation constants live directly in the generator source files.
They are never read from `.env` — the `.env` file contains only runtime config
needed by the agent.  To change them, edit the constant at the top of the
relevant file.

| Constant | Value | File | What it controls |
|---|---|---|---|
| `JOBS_PER_TECH_PER_MONTH` | `10` | jobs | Monthly capacity per technician |
| `HISTORY_MONTHS` | `24` | jobs | Calendar months of historical data to maintain |
| `FORECAST_MONTHS` | `3` | jobs | Months ahead to pre-populate with forecast jobs |
| `FUTURE_BOOKING_RATE` | `0.70` | jobs | Fraction of monthly capacity pre-committed in forecast months |
| `MONTHLY_FACTORS` | see table above | jobs | Per-trade seasonal demand multipliers (Jan–Dec) |
| `BUDGET_BUMP_PCT` | `0.35` | ads | Google recommends a 35% daily budget increase |
| `LOST_IMPRESSION_SHARE` | `0.28` | ads | Impressions lost to budget (shown on every rec) |
| `CLICKS_PER_DOLLAR` | `1.2` | ads | Estimated extra clicks per extra dollar |
| `CONVERSION_RATE` | `0.10` | ads | Estimated conversion rate for incremental clicks |

Per-contractor `sim_base_util` (generator seed) and `current_daily_budget_usd` are in
`config/contractors.py`. The agent reads `avg_6m_utilization_pct` from the view — not the seed.

---

## Resetting / regenerating

```bash
rm -rf data_out/
python -m data_generation.generate_google_ads_data --days 7 --upload
python -m data_generation.generate_jobs_data --load-bq
# Idempotent: only generates months missing from BigQuery.
# To force a full reload, truncate the jobs table in BQ first:
#   bq query --use_legacy_sql=false "TRUNCATE TABLE \`$GOOGLE_CLOUD_PROJECT.$BQ_DATASET.jobs\`"
#   python -m data_generation.generate_jobs_data --load-bq
bash scripts/run_bigquery_sql.sh
```

Generators use `--seed` (default 42) so reruns on the same month produce identical rows.

---

## Notes

- Open-Meteo is free for non-commercial use and needs no API key. For production,
  swap in a commercial provider via `WEATHER_API_BASE`.
- Sources 4–5 from the use case (conversion tracking, other paid-media channels)
  slot in as additional BigQuery tables + tools.
- All names and data in this repo are **synthetic**.
