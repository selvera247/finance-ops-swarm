# L4 / L5 / L6 → live GCP

## Already live

| | |
| --- | --- |
| Service | https://finance-ops-301858971164.us-central1.run.app |
| Project | `gen-lang-client-0611250410` |
| Method | Cloud Run **Connect repository** → Cloud Build → deploy |
| Confirm | `/health`, `/docs`, `POST /v1/bootstrap`, `POST /v1/aging` |

No service-account JSON in chat is required for this path.

## Script path (optional / CI)

One script for agent or workstation deploy (needs ADC or `GCP_SA_KEY_JSON`):

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export FINANCE_OPS_REGION=us-central1   # optional
bash scripts/go_live_gcp.sh
```

| Step | L# | Action |
| --- | --- | --- |
| Enable APIs | — | Run, AR, AI Platform, BQ, GCS, … |
| Terraform | L3/L6 | Dataset, Pub/Sub, AR, SA, embeddings bucket |
| Cloud Build | L6 | Build/push `finance-ops` image |
| Cloud Run | L6 | Deploy with public `/health` |
| Env | L4/L5 | `USE_VERTEX_VECTORS=true`, `GRAPH_BACKEND=sqlite` |
| GCS upload | L4 | Policy vector catalog → embeddings bucket |
| Smoke | — | bootstrap, aging, search, status |

## Env vars on Cloud Run

Set under **Edit & deploy new revision → Variables**:

```text
FINANCE_OPS_DATA_MODE=warehouse
FINANCE_OPS_USE_VERTEX_VECTORS=true
FINANCE_OPS_GRAPH_BACKEND=sqlite
GOOGLE_CLOUD_PROJECT=gen-lang-client-0611250410
```

## Parking lot after go-live

See [parking-lot-go-live.md](parking-lot-go-live.md):

```bash
export GOOGLE_CLOUD_PROJECT=gen-lang-client-0611250410
bash scripts/go_live_parking_lot.sh
```

- Enable BigQuery API + load tables → `go_live_bigquery.sh`
- Matching Engine index → `go_live_vector_search.py` (`SKIP_VECTOR=0`)
- Neo4j Aura or Spanner → `go_live_neo4j_aura.md` / `go_live_spanner.sh`
- ADK Agent Engine / same-image ADK → `go_live_agent_engine.sh`

See [master-plan-status.md](master-plan-status.md).
