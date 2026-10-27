# L4 · L5 · L6 complete (including live Cloud Run)

| Level | Deliverable | Local proof | Live proof |
| --- | --- | --- | --- |
| **L4** | Vertex-shaped vectors + ME simulator | `build_policy_index` + `search_policies` | `POST /v1/search_policies` after bootstrap |
| **L5** | GraphStore duckdb/sqlite/neo4j | `scripts/sync_knowledge_graph.py` | KG synced in `/v1/bootstrap` |
| **L6** | Cloud Run image + CD from GitHub | `uvicorn finance_ops.serving:app` | https://finance-ops-301858971164.us-central1.run.app |

```bash
# Local
PYTHONPATH=. python scripts/smoke_l4_l5_l6.py

# Live
curl -s https://finance-ops-301858971164.us-central1.run.app/health
curl -s -X POST https://finance-ops-301858971164.us-central1.run.app/v1/bootstrap
```

See `l4-vector-search.md`, `l5-knowledge-graph.md`, `l6-cloud-run.md`, `gcp-go-live.md`.  
Authoritative status: [master-plan-status.md](master-plan-status.md).
