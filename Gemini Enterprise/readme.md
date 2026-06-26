# Capacity-Aware Ad Budget Optimizer — Gemini Enterprise POC

A proof-of-concept that pairs Google Ads budget recommendations with a
contractor's real-world **service capacity**, so analysts approve spend increases
only when the extra leads can actually be serviced. It provisions **BigQuery +
Cloud Storage** infrastructure, loads realistic mock data, and exposes it through
a **Gemini Enterprise** agent.

---

## 1. The Problem

**Northwind Digital** manages Google Ads for home-services contractors (HVAC,
plumbing, electrical, roofing). At the beginning of every month, Google surfaces
recommendations like:

> _"Increase your Storm Damage Repair campaign budget from \$5,000/month to
> \$6,500/month — you're losing 28% of impressions to budget."_

The natural reaction is to approve: **more spend → more leads → more revenue.**

The catch: if a contractor's technicians are **already fully booked**, those
extra leads are **wasted money** — the contractor physically cannot service them.
Before approving, an analyst must cross-check the **dispatch / scheduling system**
to see whether there is spare capacity. Doing that manually for dozens of accounts
every month **does not scale**.

**Core tension:** a budget recommendation is only good advice if there is capacity
to absorb the demand it creates.

---

## 2. Proposed Solution

A **Capacity-Aware Ad Budget Optimizer** delivered as a **Gemini Enterprise
agent**. Instead of approving Google's recommendation blindly, an analyst asks the
agent in plain language:

> _"Should we approve the budget increase for CONT_ROOFING_01 in July?"_

The agent reasons over three connected signals before answering:

1. **Capacity** — how many jobs the contractor can complete per month
   (technicians × jobs-per-tech).
2. **Current load** — how many jobs are already booked for the target month
   (utilization = scheduled jobs ÷ capacity).
3. **External demand** — a weather/demand forecast that raises or lowers expected
   demand per service category (e.g. storms spike roofing demand).

**Decision rule the agent encodes:** raise budget where utilization is **low**
*and* the category demand multiplier is **high**; hold/decline where the
contractor is already near capacity, no matter how attractive the Google
recommendation looks.

This turns a manual, per-account dispatch lookup into a single natural-language
question.

---

## 3. Solution Design

### Data sources

| Signal | Store | Object | Why |
|--------|-------|--------|-----|
| Contractor capacity | BigQuery | `contractors_master` | Max jobs/month per contractor. |
| Bookings (history + future) | BigQuery | `job_ledger` | Utilization for the target month. |
| External demand | BigQuery | `weather_demand_factors` | Storm-driven demand multipliers. |
| Google Ads recommendations | Cloud Storage | `ad_recommendations/.../*.json` | The pending budget change to evaluate. |

### End-to-end flow

```
  (a) Provision infra        (b) Generate + load data        (c) Build agent
  ┌───────────────────┐      ┌────────────────────────┐      ┌──────────────────┐
  │ bigquery/*.sql    │      │ data_generation/*.py   │      │ Gemini Enterprise│
  │ -> dataset+tables │ ───► │ -> fills tables + GCS  │ ───► │ data stores +    │
  │ gsutil mb -> bucket│     │                        │      │ agent            │
  └───────────────────┘      └────────────────────────┘      └──────────────────┘
        gcloud / bq                 python                       console (no-code)
```

### Decision logic (what the agent applies)

```
utilization = scheduled_jobs(target_month) / max_monthly_capacity

if utilization is LOW and demand_multiplier is HIGH   -> APPROVE / RAISE
if utilization is HIGH (near capacity)                -> DECLINE / HOLD
otherwise                                             -> REVIEW
```

### Repository layout

```
.
├── bigquery/                         # DDL + infra provisioning (run FIRST)
│   ├── 00_create_dataset.sql
│   ├── 01_contractors_master.sql
│   ├── 02_job_ledger.sql
│   ├── 03_weather_demand_factors.sql
│   └── setup_infra.sh                # creates dataset, tables, and bucket
│
├── data_generation/                  # Python mock-data pipelines (run SECOND)
│   ├── config.py                     # central config — edit project/bucket/dataset
│   ├── gcp_utils.py                  # shared GCP client + load helpers
│   ├── contractors_pipeline.py       # -> contractors_master
│   ├── job_ledger_pipeline.py        # -> job_ledger
│   ├── weather_pipeline.py           # -> weather_demand_factors
│   ├── ad_recommendations_pipeline.py# -> GCS JSON recommendations
│   ├── run_pipeline.py               # orchestrator (runs all four)
│   └── requirements.txt
│
└── readme.md
```

---

## 4. Infrastructure & Mock Data Generation (local → GCP)

The flow is: **install gcloud → authenticate → provision infra (tables + bucket)
→ run the Python pipelines to generate and push data.**

### Prerequisites
- Python 3.10+
- A Google Cloud project with billing enabled
- The **gcloud CLI** (includes `bq` and `gsutil`)

### 4.1 Install & initialize gcloud
Install from https://cloud.google.com/sdk/docs/install, then:
```bash
gcloud init
gcloud version          # confirm gcloud, bq, gsutil are available
```

### 4.2 Authenticate
```bash
# user credentials for gcloud/bq/gsutil CLI commands
gcloud auth login

# application-default credentials used by the Python client libraries
gcloud auth application-default login

gcloud config set project project-e98a17cc-b3c1-4852-95f
```

### 4.3 Configure the project values
Edit the three constants at the top of [data_generation/config.py](data_generation/config.py):
```python
PROJECT_ID      = "project-e98a17cc-b3c1-4852-95f"
GCS_BUCKET_NAME = "northwind-digital-adsense"
BQ_DATASET_NAME = "northwind_digital_jobs"
```

### 4.4 Provision the infrastructure (BigQuery tables + GCS bucket)
Create the **dataset, the three tables, and the bucket BEFORE** running any
pipeline. Use the helper script (recommended):

```bash
export PROJECT_ID="project-e98a17cc-b3c1-4852-95f"
export GCS_BUCKET_NAME="northwind-digital-adsense"
./bigquery/setup_infra.sh
```

The script enables the required APIs, applies each DDL file (substituting your
project id), and creates the bucket if it does not already exist.

<details>
<summary>Prefer to run the steps manually?</summary>

```bash
# 1. Enable APIs
gcloud services enable bigquery.googleapis.com storage.googleapis.com

# 2. Create the dataset + tables (the project id is already set in the .sql files)
bq query --use_legacy_sql=false < bigquery/00_create_dataset.sql
bq query --use_legacy_sql=false < bigquery/01_contractors_master.sql
bq query --use_legacy_sql=false < bigquery/02_job_ledger.sql
bq query --use_legacy_sql=false < bigquery/03_weather_demand_factors.sql

# 3. Create the bucket
gsutil mb -l US gs://$GCS_BUCKET_NAME
```
</details>

> The tables are created empty. The pipelines load into them with `WRITE_TRUNCATE`,
> so re-running a pipeline replaces the rows without altering the schema.

### 4.5 Install Python dependencies
```bash
cd data_generation
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4.6 Generate and push the data
Run from inside the `data_generation/` folder (the modules import each other as siblings):
```bash
python run_pipeline.py
```
Or run a single pipeline (contractors must run first):
```bash
python contractors_pipeline.py
python job_ledger_pipeline.py
python weather_pipeline.py
python ad_recommendations_pipeline.py
```

### What gets generated

**BigQuery tables (dataset `northwind_digital_jobs`)**

| Table | Description | Rows |
|-------|-------------|------|
| `contractors_master` | Contractor catalog with capacity (`num_technicians * jobs_per_tech_month`). | 12 |
| `job_ledger` | Historical `COMPLETED` jobs (2024-06 → 2026-06) **plus** future `SCHEDULED` jobs for 2026-07. | thousands |
| `weather_demand_factors` | Per-category demand multipliers for the 2026-07 `SEVERE_STORMS` forecast. | 1 |

- **Capacity signal:** for 2026-07, some contractors are intentionally **heavily
  booked (~90% capacity)** and others **lightly booked (~30% capacity)** — so the
  agent has clear winners and losers to reason about.
- **Demand signal:** the 2026-07 storm forecast boosts Roofing (1.8×), Plumbing
  (1.5×), Electrician (1.3×); HVAC stays neutral (1.0×).

**GCS — Ad Recommendations (JSON)**
- Path: `gs://[BUCKET]/ad_recommendations/year=2026/month=07/rec_[CONTRACTOR_ID].json`
- One `BUDGET_RAISE` document per contractor with projected impact and a
  `PENDING_REVIEW` status — the recommendation the analyst must accept or reject.

### 4.7 Verify
```bash
# July booking load vs capacity (the core utilization signal)
bq query --use_legacy_sql=false "
SELECT j.contractor_id, c.max_monthly_capacity,
       COUNT(*) AS scheduled_jobs,
       ROUND(COUNT(*) / c.max_monthly_capacity, 2) AS utilization
FROM \`project-e98a17cc-b3c1-4852-95f.northwind_digital_jobs.job_ledger\` j
JOIN \`project-e98a17cc-b3c1-4852-95f.northwind_digital_jobs.contractors_master\` c USING (contractor_id)
WHERE j.target_completion_month = '2026-07' AND j.job_status = 'SCHEDULED'
GROUP BY 1, 2 ORDER BY utilization DESC"

# JSON recommendations in GCS
gsutil ls gs://northwind-digital-adsense/ad_recommendations/year=2026/month=07/
gsutil cat gs://northwind-digital-adsense/ad_recommendations/year=2026/month=07/rec_CONT_HVAC_01.json
```

---

## 5. Set Up in Gemini Enterprise (step by step)

After Section 4 has provisioned the infra and loaded the data, connect it to a
Gemini Enterprise agent.

### Step 0 — One-time prerequisites
1. Enable these APIs in the Cloud Console:
   - **Gemini Enterprise / Discovery Engine API** (`discoveryengine.googleapis.com`)
   - **BigQuery API**, **Cloud Storage API**
2. Grant your user:
   - `roles/discoveryengine.admin`
   - `roles/bigquery.dataViewer` on `northwind_digital_jobs`
   - `roles/storage.objectViewer` on the bucket
3. Open the **Gemini Enterprise / AI Applications** console:
   `https://console.cloud.google.com/gen-app-builder`

### Step 1 — BigQuery data stores (structured)
1. **Data Stores → Create Data Store → BigQuery.**
2. Select table `project-e98a17cc-b3c1-4852-95f.northwind_digital_jobs.contractors_master`,
   data type **Structured**, name it `ds-contractors`, **Create**.
3. Repeat for `job_ledger` (`ds-job-ledger`) and `weather_demand_factors`
   (`ds-weather`).

### Step 2 — Cloud Storage data store (unstructured JSON)
1. **Create Data Store → Cloud Storage.**
2. Prefix: `gs://northwind-digital-adsense/ad_recommendations/`.
3. Import as **Unstructured documents**, name it `ds-ad-recommendations`, **Create**.
4. Wait until status is **Active** (JSON indexing can take a few minutes).

### Step 3 — Create the agent
1. **Apps → Create App → Agent** (conversational).
2. Attach all four data stores (`ds-contractors`, `ds-job-ledger`, `ds-weather`,
   `ds-ad-recommendations`).
3. Name it **"Ad Budget Optimizer Assistant"**, pick a region, **Create**.

### Step 4 — Agent instructions
In **Configuration → Instructions**, paste:

> You help Northwind Digital analysts decide whether to approve Google Ads budget
> increases for home-services contractors. Before recommending approval, check
> capacity and load: use `contractors_master` for `max_monthly_capacity`,
> `job_ledger` for bookings (`target_completion_month = '2026-07'`,
> `job_status = 'SCHEDULED'`), and `weather_demand_factors` for the category demand
> multiplier. Compute utilization = scheduled jobs ÷ max_monthly_capacity.
> Recommend APPROVING/raising budget only when utilization is well below 1.0 AND
> the category's demand multiplier is high. If the contractor is near capacity,
> advise HOLDING the budget because extra leads cannot be serviced. Reference the
> matching GCS ad recommendation document when discussing a pending change.

### Step 5 — Publish
Open **Preview / Integration**, enable the web preview, and start chatting.

---

## 6. Test the Agent

Use these prompts in the preview to validate the setup.

| Test | Prompt | Expected behavior |
|------|--------|-------------------|
| Capacity lookup | "What is the maximum monthly capacity of CONT_ROOFING_01?" | Returns the value from `contractors_master`. |
| Utilization | "Which contractors are lightly booked for July 2026?" | Lists contractors at ~30% utilization. |
| Demand signal | "What does the July storm forecast mean for roofing demand?" | Explains the 1.8× roofing multiplier (SEVERE_STORMS). |
| **Core decision** | "Google suggests raising the budget for CONT_ROOFING_01 in July — should we approve?" | Approves only if utilization is low; otherwise advises HOLD because techs are booked. |
| Capacity guardrail | "Approve the budget increase for a contractor that is 90% booked in July." | Declines / cautions — extra leads can't be serviced. |
| Document retrieval | "Show the pending ad recommendation for CONT_HVAC_01." | Surfaces the GCS JSON with status PENDING_REVIEW. |

### Validate against source data
Cross-check answers with the utilization query in [Step 4.7](#47-verify). The
contractors the agent approves should be those with the **lowest** utilization and
the **highest** category demand multiplier.

### Troubleshooting
| Symptom | Fix |
|---------|-----|
| Data store stuck "Indexing" | GCS JSON indexing takes a few minutes; refresh later. |
| Agent can't find a table | Confirm the data store synced and names match `config.py`. |
| "Permission denied" on import | Grant `bigquery.dataViewer` / `storage.objectViewer` to the Gemini Enterprise service account. |
| Empty answers | Re-run `python run_pipeline.py`, then re-sync the data store. |
| Stale results after re-load | Trigger a manual re-sync (or use Periodic sync). |

---

## Re-running / Cleanup
- Pipelines use `WRITE_TRUNCATE`, so re-running `run_pipeline.py` replaces table contents cleanly.
- Remove GCS objects: `gsutil -m rm -r gs://northwind-digital-adsense/ad_recommendations/`
- Drop the dataset: `bq rm -r -f -d project-e98a17cc-b3c1-4852-95f:northwind_digital_jobs`
