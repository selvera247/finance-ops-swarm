# Demo reactivate (Spanner + Matching Engine)

Use after idle teardown. Cloud Run can stay up on BigQuery + sqlite + local ME sim.
These steps restore **managed graph** and **live Vector Search** for a demo, then you can tear down again with [demo-teardown.md](demo-teardown.md).

**Project:** `gen-lang-client-0611250410`  
**Region:** `us-central1`  
**Service:** `finance-ops`  
**URL:** https://finance-ops-301858971164.us-central1.run.app

Run from a clone of `main` in PowerShell (no bash required).

```powershell
cd C:\Users\Selvera\finance_agents   # or your clone path
git checkout main
git pull origin main

$PROJECT = "gen-lang-client-0611250410"
$REGION  = "us-central1"
$SERVICE = "finance-ops"
$ROOT    = (Get-Location).Path
gcloud config set project $PROJECT
gcloud auth application-default set-quota-project $PROJECT
```

---

## A. Spanner graph (L5)

```powershell
$INSTANCE = "finance-ops"
$DATABASE = "finance_ops"
$CONFIG   = "regional-$REGION"

gcloud services enable spanner.googleapis.com --project=$PROJECT

gcloud spanner instances describe $INSTANCE --project=$PROJECT 2>$null
if ($LASTEXITCODE -ne 0) {
  gcloud spanner instances create $INSTANCE `
    --config=$CONFIG `
    --description="Finance ops KG" `
    --nodes=1 `
    --project=$PROJECT
}

gcloud spanner databases create $DATABASE --instance=$INSTANCE --project=$PROJECT 2>$null

gcloud spanner databases ddl update $DATABASE `
  --instance=$INSTANCE `
  --project=$PROJECT `
  --ddl-file="$ROOT\data_plane\graph\spanner_schema.sql"

$env:GOOGLE_CLOUD_PROJECT = $PROJECT
$env:FINANCE_OPS_GRAPH_BACKEND = "spanner"
$env:SPANNER_INSTANCE = $INSTANCE
$env:SPANNER_DATABASE = $DATABASE
$env:PYTHONPATH = $ROOT

# venv with google-cloud-spanner + duckdb if needed
pip install google-cloud-spanner duckdb -q
python scripts\sync_knowledge_graph.py --backend spanner --export

# Runtime SA needs Spanner access
$SA = gcloud run services describe $SERVICE --region=$REGION --format="value(spec.template.spec.serviceAccountName)"
if (-not $SA) { $SA = "$PROJECT@appspot.gserviceaccount.com" }
# Often: 301858971164-compute@developer.gserviceaccount.com
gcloud spanner databases add-iam-policy-binding $DATABASE `
  --instance=$INSTANCE `
  --member="serviceAccount:$SA" `
  --role="roles/spanner.databaseUser"

gcloud run services update $SERVICE `
  --region=$REGION `
  --project=$PROJECT `
  --update-env-vars="FINANCE_OPS_GRAPH_BACKEND=spanner,SPANNER_INSTANCE=$INSTANCE,SPANNER_DATABASE=$DATABASE,GOOGLE_CLOUD_PROJECT=$PROJECT"
```

**Success:** `/v1/status` → `graph.backend=spanner`, `ok=true`, `nodes` ≥ 16.

> Cloud Run image must include the Spanner `multi_use` snapshot fix (on `main` after PR #7).

---

## B. Matching Engine / Vector Search (L4)

Long-running (index create + deploy often 30–90+ minutes).

```powershell
.\.venv\Scripts\Activate.ps1
pip install google-cloud-aiplatform google-cloud-storage -q

$env:GOOGLE_CLOUD_PROJECT = $PROJECT
$env:FINANCE_OPS_REGION = $REGION
$env:PYTHONPATH = $ROOT
$env:CLOUD_RUN_SERVICE = $SERVICE

gcloud services enable aiplatform.googleapis.com --project=$PROJECT
python scripts\go_live_vector_search.py
```

Script will: ensure embeddings bucket → build/upload `me_datapoints.json` → create index → create endpoint → deploy `finance_ops_policies` → set Cloud Run:

- `FINANCE_OPS_USE_VERTEX_VECTORS=true`
- `FINANCE_OPS_VECTOR_INDEX_ENDPOINT=projects/.../indexEndpoints/...`
- `FINANCE_OPS_VECTOR_DEPLOYED_INDEX_ID=finance_ops_policies`

**Success:** `/v1/status` → `vectors.index_endpoint` non-null, `active_backend=vertex_vector_search`.

Last known IDs (from 2026-10-20; **recreate** after teardown — new IDs each time):

| Resource | Example ID (historical) |
| --- | --- |
| Index | `indexes/201771378813173760` |
| Endpoint | `indexEndpoints/5910453342412210176` |
| Deployed id | `finance_ops_policies` |
| Bucket | `gs://gen-lang-client-0611250410-finance-ops-embeddings` |

---

## C. Confirm both

```powershell
Invoke-RestMethod "https://finance-ops-301858971164.us-central1.run.app/v1/status" |
  ConvertTo-Json -Depth 6

Invoke-RestMethod -Method POST `
  -Uri "https://finance-ops-301858971164.us-central1.run.app/v1/aging" `
  -ContentType "application/json" `
  -Body '{"customer_id":"CUST-ACME"}'
# expect total_open ~ 16700 from BigQuery
```

---

## D. Agent Engine playground (optional)

Already deployed once; reopen:

https://console.cloud.google.com/vertex-ai/agents/agent-engines/locations/us-central1/agent-engines/4038238202861977600/playground?project=301858971164

Redeploy if deleted:

```powershell
adk deploy agent_engine `
  --project=$PROJECT `
  --region=us-central1 `
  --display_name=finance-ops `
  finance_ops
```

Do **not** set `FINANCE_OPS_SERVE_MODE=adk` on Cloud Run (keeps `/v1/*` as the HTTP surface).

---

## After the demo

See [demo-teardown.md](demo-teardown.md) — undeploy/delete ME, delete Spanner instance, reset Cloud Run env to sqlite + clear `FINANCE_OPS_VECTOR_INDEX_ENDPOINT`.
