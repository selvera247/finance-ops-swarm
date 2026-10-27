# Master plan status (reassessment)

**As of:** 2026-10-20  
**Verdict:** Master plan **complete** — local demo + narrative + Slack HITL + L3–L6 code + **live Cloud Run**. Parking-lot go-live scripts are in-repo; live BQ/ME/Spanner/Agent Engine need project ADC/SA.

## Live proof

| Check | Result |
| --- | --- |
| Service | https://finance-ops-301858971164.us-central1.run.app |
| Project | `gen-lang-client-0611250410` |
| `/health` | `status=ok` |
| `POST /v1/bootstrap` | warehouse + vectors OK |
| `POST /v1/aging` `CUST-ACME` | `total_open=16700` |
| Deploy path | GitHub continuous deploy → Cloud Build → Cloud Run |

Swagger: `/docs` · bare `/` returns FastAPI `Not Found` (expected).

## Plan scorecard

| Pillar | Status |
| --- | --- |
| Data → AI (warehouse → agents → evidence) | **Done** (ADK live) |
| GUI unlock (Playwright + drop zones) | **Done** |
| Runtime (#11/#12/#1/#5/#8/#10) | **Done** |
| L7 CFO/CTO one-pager | **Done** |
| L3 BigQuery mode + DuckDB fallback | **Done** (code); live BQ load via parking-lot script |
| Slack HITL (#8) | **Done** (`#all-demo`) |
| L4 vectors (Vertex-shaped + ME sim) | **Done** (live API search after bootstrap) |
| L5 graph store (duckdb/sqlite/neo4j/spanner) | **Done** (live bootstrap syncs KG; managed via scripts) |
| L6 Cloud Run | **Done** (URL above) |

## Parking lot (scripts ready — run with SA/ADC)

See [parking-lot-go-live.md](parking-lot-go-live.md).

1. Enable BigQuery API + load demo tables (L3 live BQ reads) → `go_live_bigquery.sh`
2. Deploy Vertex Matching Engine index + `FINANCE_OPS_VECTOR_INDEX_ENDPOINT` → `go_live_vector_search.py`
3. Managed Neo4j / Spanner Graph → `go_live_neo4j_aura.md` / `go_live_spanner.sh`
4. ADK Agent Engine on the same image → `go_live_agent_engine.sh` + `FINANCE_OPS_SERVE_MODE=adk`
5. Agent Engineer craft: MCP · memory · sandbox · sanitize · self-heal · context budget · shadow trajectories.

```bash
export GOOGLE_CLOUD_PROJECT=gen-lang-client-0611250410
bash scripts/go_live_parking_lot.sh
```

## How to re-confirm “all done”

```bash
BASE=https://finance-ops-301858971164.us-central1.run.app
curl -s $BASE/health
curl -s -X POST $BASE/v1/bootstrap
curl -s -X POST $BASE/v1/aging -H 'Content-Type: application/json' \
  -d '{"customer_id":"CUST-ACME"}'
```
