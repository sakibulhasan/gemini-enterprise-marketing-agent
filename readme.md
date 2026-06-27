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
│   ├── tests/                        # pytest unit tests for the generators
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

# Point gcloud at YOUR project. List the projects your account can access:
gcloud projects list
# then set the one you want to use (replace with your own project id):
gcloud config set project YOUR_PROJECT_ID
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
# Use YOUR project id and a bucket name you create/choose (must be globally unique).
export PROJECT_ID="YOUR_PROJECT_ID"
export GCS_BUCKET_NAME="YOUR_BUCKET_NAME"
./bigquery/setup_infra.sh
```

The script enables the required APIs, applies each DDL file (substituting your
project id), and creates the bucket if it does not already exist.

<details>
<summary>Prefer to run the steps manually?</summary>

```bash
# 1. Enable APIs
gcloud services enable bigquery.googleapis.com storage.googleapis.com

# 2. Create the dataset + tables (substitute your project id into the DDL)
for f in bigquery/0*.sql; do
  sed "s/YOUR_PROJECT_ID/$PROJECT_ID/g" "$f" | bq query --use_legacy_sql=false
done

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
| `job_ledger` | Historical `COMPLETED` jobs (rolling **last 2 years**) **plus** future `SCHEDULED` jobs for the **next 3 months** (relative to the run date). | thousands |
| `weather_demand_factors` | Per-category demand multipliers for the `SEVERE_STORMS` forecast, one row per forecast month (current month + next 2). | 3 |

- **Capacity signal:** for each upcoming month, some contractors are intentionally
  **heavily booked (~90% capacity)** and others **lightly booked (~30% capacity)** — so the
  agent has clear winners and losers to reason about.
- **Demand signal:** the storm forecast boosts Roofing (1.8×), Plumbing
  (1.5×), Electrician (1.3×); HVAC stays neutral (1.0×).

**GCS — Ad Recommendations (JSON)**
- One `BUDGET_RAISE` document per contractor for the **current month and the next
  month** (relative to the run date), each with projected impact and a
  `PENDING_REVIEW` status — the recommendation the analyst must accept or reject.
- Path (Hive-partitioned, derived from each recommendation's target month):
  `gs://[BUCKET]/ad_recommendations/year=[YYYY]/month=[MM]/rec_[CONTRACTOR_ID].json`

### 4.7 Verify
```bash
# Next-month booking load vs capacity (the core utilization signal).
# Replace 2026-07 with the month you want to inspect.
bq query --use_legacy_sql=false "
SELECT j.contractor_id, c.max_monthly_capacity,
       COUNT(*) AS scheduled_jobs,
       ROUND(COUNT(*) / c.max_monthly_capacity, 2) AS utilization
FROM \`project-e98a17cc-b3c1-4852-95f.northwind_digital_jobs.job_ledger\` j
JOIN \`project-e98a17cc-b3c1-4852-95f.northwind_digital_jobs.contractors_master\` c USING (contractor_id)
WHERE j.target_completion_month = '2026-07' AND j.job_status = 'SCHEDULED'
GROUP BY 1, 2 ORDER BY utilization DESC"

# JSON recommendations in GCS (year/month are derived from the target month)
gsutil ls -r gs://northwind-digital-adsense/ad_recommendations/
gsutil cat gs://northwind-digital-adsense/ad_recommendations/year=2026/month=07/rec_CONT_HVAC_01.json
```

### 4.8 Run the tests
The data-generation logic ships with offline unit tests (no GCP credentials
needed — they exercise the pure `generate()` / `build_recommendation()` functions).
Run them from inside `data_generation/` with the same virtualenv from step 4.5
activated:
```bash
python -m pytest -q
```
> If you see `No module named pytest`, your virtualenv predates pytest being
> added to `requirements.txt` — just re-run `pip install -r requirements.txt`.

The suite verifies the contractor roster (12 rows, capacity math), the job
ledger (historical 2-year window + future 3-month schedule, unique ids, booking
dates before their target month), the weather forecast months/multipliers, and
the ad-recommendation target months and document shape.

---

## 5. Set Up in Gemini Enterprise (step by step)

After Section 4 has provisioned the infra and loaded the data, connect it to a
Gemini Enterprise agent.

### Step 0 — One-time prerequisites (Web Console)

> Throughout this section, use the **search box at the top of the Cloud Console**
> (the bar labelled *"Search (/) for resources, docs, products, and more"*). Type
> the product/page name, then pick the matching result — no need to memorize URLs.

**0.1 Select your project**
1. Open the Cloud Console at `console.cloud.google.com` and sign in.
2. In the **top blue bar**, click the project picker and select **your** project
   (the same one used in Section 4). Confirm its name shows in the bar.

**0.2 Enable the required APIs**
Gemini Enterprise is built on the **Discovery Engine API** — so yes, you need it,
along with BigQuery and Cloud Storage. Enable each one from its API page:
1. Click the **top search box**, type **`Discovery Engine API`**, and select the
   result under *Marketplace / APIs*. On its page, make sure your project is
   selected and click **Enable**.
2. Repeat: search **`BigQuery API`** → open the result → **Enable**.
3. Repeat: search **`Cloud Storage API`** → open the result → **Enable**.

> Tip: if you click **Activate** on the Gemini Enterprise landing page (next step),
> the console enables the Discovery Engine API for you automatically — but checking
> the page above confirms it is on.

**0.3 Open / activate Gemini Enterprise**
1. Click the **top search box** and type **`Gemini Enterprise`** (it may also appear
   as **`AI Applications`** or **`Agent Builder`** — they are the same product).
   Select the matching result.
2. Confirm the project selector in the top bar shows **your** project.
3. If prompted, click **Activate** / **Continue** and accept the terms of service.
   This is a one-time activation per project.

**0.4 Grant yourself the needed IAM roles**
1. In the **top search box**, type **`IAM`** and select **IAM** (under *IAM & Admin*).
2. Find your own user (the email you logged in with) and click the **pencil
   (Edit principal)** icon on that row.
3. Click **＋ ADD ANOTHER ROLE** and add each of these (one per role):
   - **Discovery Engine Admin** (`roles/discoveryengine.admin`) — create data
     stores + agents.
   - **BigQuery Data Viewer** (`roles/bigquery.dataViewer`) — read the tables.
   - **Storage Object Viewer** (`roles/storage.objectViewer`) — read the GCS JSON.
4. Click **Save**.

> If you are the project **Owner**, you already have these permissions and can
> skip 0.4 — but adding them explicitly is harmless.

**0.5 Verify you're ready**
1. In the **top search box**, type **`Enabled APIs`** and select
   **Enabled APIs & services** (under *APIs & Services*).
2. Confirm **Discovery Engine API**, **BigQuery API**, and **Cloud Storage API**
   all appear in the list. Now continue to Step 1.

### Step 1 — BigQuery data stores (structured)

You will create **one data store per BigQuery table** (three in total). The
*Create data store* wizard has four steps shown on the left:
**Source → Data → Schema → Configuration**. Repeat the whole flow for each table.

**1.1 Source — start a new data store and pick BigQuery**
1. In the left nav of the Gemini Enterprise console, click **Data stores**.
2. Click **＋ CREATE DATA STORE**.
3. On the **Source** step, choose **BigQuery**.

**1.2 Data — choose the import type, frequency, and table**
On the **Import data from BigQuery** screen:
4. **What kind of data are you importing?** → under *Structured Data Import*,
   select **BigQuery table with your own schema** (the schema is auto-detected).
5. **Synchronization frequency** → leave **One time** for the POC.
6. **Select a table you want to import** → in the **BigQuery path** field click
   **Browse** (or type it directly using the format `projectId.datasetId.tableId`):
   `YOUR_PROJECT_ID.northwind_digital_jobs.contractors_master`.
7. Click **Continue**.

**1.3 Schema — confirm the auto-detected fields**
8. Review the auto-detected columns (no changes needed for the POC) and click
   **Continue**.

**1.4 Configuration — name and create**
9. Enter the **Data store name**: `ds-contractors`.
10. Click **Create**. (Row indexing runs in the background — you don't have to wait
    before creating the next one.)

**1.5 Repeat for the other two tables**
- `job_ledger` → data store name **`ds-job-ledger`**
- `weather_demand_factors` → data store name **`ds-weather`**

When done you should have three structured data stores: `ds-contractors`,
`ds-job-ledger`, `ds-weather`.

### Step 2 — Cloud Storage data store (unstructured JSON)

The ad-recommendation JSON files are imported as **unstructured documents**. This
wizard has three steps: **Source → Data → Configuration**.

**2.1 Source — start a new data store and pick Cloud Storage**
1. In the left nav, click **Data stores**, then **＋ CREATE DATA STORE**.
2. On the **Source** step, choose **Cloud Storage**.

**2.2 Data — choose the import type, frequency, and path**
On the **Import data from Cloud Storage** screen:
3. **What kind of data are you importing?** → under *Unstructured Data Import
   (Document Search & RAG)*, select **Documents** (handles JSON/PDF/HTML/TXT, etc.).
4. **Synchronization frequency** → leave **One time** for the POC.
5. **Select a folder or a file you want to import** → keep the **Folder** toggle,
   then in the `gs://` field click **Browse** (or type it) and point at:
   `gs://YOUR_BUCKET_NAME/ad_recommendations/`
   (all files under it are imported recursively).
6. Click **Continue**.

**2.3 Configuration — name and create**
7. Enter the **Data store name**: `ds-ad-recommendations`.
8. Click **Create**.
9. Wait until its status shows **Active** — JSON indexing can take a few minutes.

### Step 3 — Create the agent (App)

**3.1 Start a new app**
1. In the left nav, click **Apps**, then **＋ CREATE APP** (this opens the
   **Create** form directly — no app-type prompt).

**3.2 Choose a display name**
2. **App name** → enter `Ad Budget Optimizer Assistant`.
3. Note the auto-generated **ID** shown beneath the name — it **cannot be changed
   later** (use **Edit** now if you want a custom id).

**3.3 Choose a location**
4. **Multi-region** → leave **global (Global)** (recommended unless you have a
   compliance reason to pin a region — this also can't be changed later).

**3.4 Advanced options (optional)**
5. Expand **Advanced options** if you want to set them — both are optional for the POC:
   - **Provide the external name of your company** → e.g. `Northwind Digital`
     (helps the model give higher-quality responses).
   - **Include cross-domain documents** → leave **unchecked** (only relevant for
     Google Drive connectors outside your organization).

**3.5 Create the app**
6. Click **Create**. You'll see **"App created successfully"** and land on the
   app's **Overview** page (left nav: *Overview, Connected data stores, Actions,
   Prompt chips, Configurations, Agents, Security, Integration*).

**3.6 Attach the four data stores**
7. In the app's left nav, click **Connected data stores**. (It starts empty —
   *"No data stores are connected to this Gemini Enterprise app yet."*)
8. Click **🔗 Add existing data stores** (use this since you already created them in
   Steps 1–2; **＋ New data store** is only for creating a brand-new one here).
9. Select **all four** — `ds-contractors`, `ds-job-ledger`, `ds-weather`,
   `ds-ad-recommendations` — and confirm.
10. They now appear in the list with their **Type**, **Status**, and sync columns.

### Step 4 — Assistant behavior & instructions

With the four data stores connected (Step 3), the built-in **Core Assistant**
already grounds its answers on them — you don't have to "wire up" anything for it
to read your tables and JSON. What's left is to (optionally) give it guidance and
verify it works.

> Heads-up: clicking **Agents → Core Assistant** opens a **read-only registry
> page** (Display name, Description, SPIFFE ID, tabs *Details / Traces / Metrics /
> Observability*). There is **no instructions field** there — that page is just
> metadata. Assistant behavior is configured under **Configurations**, below.

**4.1 Open the assistant configuration**
1. In the app's left sidebar, click **Configurations**. It opens on the
   **Search UI** tab by default (tabs across the top: *Autocomplete, Search UI,
   Control, **Assistant**, Knowledge Graph, Feature Management, Observability*).
2. Click the **Assistant** tab.

**4.2 Add the system instructions**
3. On the **Assistant** tab you'll see **Gemini Enterprise-only settings** with
   an **Additional LLM system instructions** section.
4. Select **Customize** (instead of *Use default*). A text field appears.
5. Paste the instructions below into it:

   > You help Northwind Digital analysts decide whether to approve Google Ads
   > budget increases for home-services contractors. Before recommending approval,
   > check capacity and load: use `contractors_master` for `max_monthly_capacity`,
   > `job_ledger` for bookings (`target_completion_month` = the month being asked
   > about, `job_status = 'SCHEDULED'`), and `weather_demand_factors` for the
   > category demand multiplier. Compute utilization = scheduled jobs ÷
   > max_monthly_capacity. Recommend APPROVING/raising budget only when utilization
   > is well below 1.0 AND the category's demand multiplier is high. If the
   > contractor is near capacity, advise HOLDING the budget because extra leads
   > cannot be serviced. Reference the matching GCS ad recommendation document when
   > discussing a pending change.

**4.3 Review the other settings on this page**
   - **Enable web grounding** — optionally turn this **off** so the assistant only
     answers from your connected data stores rather than the public web.
   - **Default Web Search State**, **Enable location context**, **Enable Model
     Armor**, **Banned phrases**, **Chat history retention period** — leave at
     defaults for the POC.

**4.4 Save**
6. Click **Save and publish** at the bottom of the page.

### Step 5 — Test the assistant

The **Test config** chat panel is available on the right side of the
**Configurations → Search UI** tab. No identity provider or web-app publishing
is needed to use it.

> **Note on the Identity provider / Integration page:** Clicking **Integration**
> prompts you to choose an identity provider. If you see the error *"Project's GCP
> Organization is not associated with a Cloud Identity customer id"*, your GCP
> project was created with a personal account that is not under a Google Workspace
> org. This only blocks web-app publishing — it does **not** affect the Test
> config panel below. Skip Integration for now and use the steps below to validate
> the assistant.

**5.1 Open the Test config panel**
1. In the app's left sidebar, click **Configurations**.
2. Make sure the **Search UI** tab is selected (it's the default). The
   **Test config** panel appears on the right half of the page, showing
   *"Hello, gemini — Let's get some work done!"* with an input box labelled
   *"Ask anything, search your data, @mention or /tools"*.

**5.2 Run a grounding check**
3. In the **Test config** input box, type the question below and press **Enter**:

   > *What is the max monthly capacity of CONT_ROOFING_01?*

4. If the assistant returns a value sourced from `contractors_master`, your data
   stores are connected correctly. Move on to Section 6 for the full test suite.

**5.3 (Optional) Publish as a web app**
If your GCP project is under a Google Workspace / Cloud Identity organization:
1. In the left sidebar, click **Integration**.
2. Select **Use Google Identity** and click **Confirm Workforce Identity**.
3. On the Integration page, find the **Web app** section → **Enable** / **Create**.
4. Set the access policy (restrict to your org or allow public), click
   **Save and publish**, and copy the shareable URL.

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
