# Demo teardown (stop Spanner + Matching Engine idle cost)

Keeps Cloud Run + BigQuery demo tables. Drops paid Spanner and ME replicas.

```powershell
$PROJECT = "gen-lang-client-0611250410"
$REGION  = "us-central1"
$SERVICE = "finance-ops"
gcloud config set project $PROJECT
```

## 1. Matching Engine

List endpoints if IDs unknown:

```powershell
gcloud ai index-endpoints list --region=$REGION --project=$PROJECT
gcloud ai indexes list --region=$REGION --project=$PROJECT
```

Undeploy then delete (IDs change each reactivate):

```powershell
$ENDPOINT = "projects/301858971164/locations/us-central1/indexEndpoints/ENDPOINT_ID"
$INDEX    = "projects/301858971164/locations/us-central1/indexes/INDEX_ID"
$DEPLOYED = "finance_ops_policies"

gcloud ai index-endpoints undeploy-index $ENDPOINT `
  --deployed-index-id=$DEPLOYED --region=$REGION --project=$PROJECT

gcloud ai index-endpoints delete $ENDPOINT --region=$REGION --project=$PROJECT --quiet
gcloud ai indexes delete $INDEX --region=$REGION --project=$PROJECT --quiet
```

`NOT_FOUND` on undeploy = already gone (OK).

## 2. Spanner

```powershell
gcloud spanner instances delete finance-ops --project=$PROJECT --quiet
```

## 3. Cloud Run cheap defaults

```powershell
gcloud run services update $SERVICE `
  --region=$REGION `
  --project=$PROJECT `
  --update-env-vars="FINANCE_OPS_GRAPH_BACKEND=sqlite,FINANCE_OPS_USE_VERTEX_VECTORS=true" `
  --remove-env-vars="FINANCE_OPS_VECTOR_INDEX_ENDPOINT,SPANNER_INSTANCE,SPANNER_DATABASE"
```

**Expect:** `data_mode=bigquery`, `graph.backend=sqlite`, `index_endpoint=null`, `active_backend=vertex_embed_local_me`.

Optional: `POST /v1/bootstrap` to refill sqlite KG for demos without Spanner.

## 4. Agent Engine (idle cost)

Managed reasoning engine from `adk deploy agent_engine` (demo id was
`4038238202861977600` — confirm before delete):

```powershell
$PROJECT = "gen-lang-client-0611250410"
$REGION  = "us-central1"
$ENGINE  = "4038238202861977600"   # list first if unsure

# List
curl -sS -H "Authorization: Bearer $(gcloud auth print-access-token)" `
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${REGION}/reasoningEngines"

# Delete
curl -sS -X DELETE -H "Authorization: Bearer $(gcloud auth print-access-token)" `
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${REGION}/reasoningEngines/${ENGINE}"
```

Or Console → Vertex AI → Agent Engine → delete. Cloud Run HTTP API stays the live surface.
Or: `bash scripts/delete_agent_engine.sh`

## 5. Optional

- GitHub PATs: never paste in chat; revoke at https://github.com/settings/tokens if exposed.
- Delete merged remote branches: `git push origin --delete cursor/<merged-branch>`
