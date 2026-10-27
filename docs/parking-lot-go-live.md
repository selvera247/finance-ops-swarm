# Parking lot → live GCP

Scripts to finish optional live wiring after Cloud Run is up.

| # | Goal | Script |
| --- | --- | --- |
| 1 | Enable BigQuery API + load demo tables + `FINANCE_OPS_DATA_MODE=bigquery` | `scripts/go_live_bigquery.sh` |
| 2 | Vertex Matching Engine index + `FINANCE_OPS_VECTOR_INDEX_ENDPOINT` | `scripts/go_live_vector_search.py` |
| 3a | Managed Neo4j Aura | `scripts/go_live_neo4j_aura.md` |
| 3b | Spanner Graph–shaped tables | `scripts/go_live_spanner.sh` |
| 4 | ADK Agent Engine (same codebase / image dual entry) | `scripts/go_live_agent_engine.sh` |

Orchestrator (Vector Search skipped by default — long ME create):

```bash
export GOOGLE_CLOUD_PROJECT=gen-lang-client-0611250410
# export GCP_SA_KEY_JSON=/path/to/sa.json   # or ADC
bash scripts/go_live_parking_lot.sh
# Matching Engine when ready:
SKIP_BQ=1 SKIP_SPANNER=1 SKIP_AGENT_ENGINE=1 SKIP_VECTOR=0 bash scripts/go_live_parking_lot.sh
```

## Same image: HTTP vs ADK

`Dockerfile` → `deploy/entrypoint.sh`:

| `FINANCE_OPS_SERVE_MODE` | Process |
| --- | --- |
| `http` (default) | `uvicorn finance_ops.serving:app` — live Cloud Run today |
| `adk` | `adk api_server` on the same image |

Agent Engine managed deploy: `adk deploy agent_engine` via `go_live_agent_engine.sh`  
(config: `finance_ops/.agent_engine_config.json`).

## Auth

Needs project `gen-lang-client-0611250410` ADC or `GCP_SA_KEY_JSON` with BigQuery, Vertex AI, Storage, Cloud Run Admin, Spanner Admin (or Editor).

## After idle teardown / next demo

- Turn Spanner + Matching Engine back on: [demo-reactivate.md](demo-reactivate.md)
- Stop idle cost again: [demo-teardown.md](demo-teardown.md)
