# L6 — Cloud Run deploy

## Live

| | |
| --- | --- |
| URL | https://finance-ops-301858971164.us-central1.run.app |
| Docs | https://finance-ops-301858971164.us-central1.run.app/docs |
| Project | `gen-lang-client-0611250410` |
| Path used | GitHub continuous deploy (Cloud Build → Cloud Run) |

```bash
curl -s https://finance-ops-301858971164.us-central1.run.app/health
# bare / returns {"detail":"Not Found"} — use /health or /docs
```

## What shipped in-repo

- `Dockerfile` + `finance_ops/serving.py` (FastAPI `/health`, bootstrap, aging, RAG, HITL)
- `infra/terraform` — Artifact Registry, SA IAM, Cloud Run v2, embeddings bucket, BQ, Pub/Sub
- `scripts/deploy_cloud_run.sh` · `scripts/go_live_gcp.sh`
- `docker-compose.yml` for local API + Neo4j

## Local API smoke

```bash
pip install -r requirements.txt -r requirements-cloud.txt
PYTHONPATH=. uvicorn finance_ops.serving:app --port 8080
curl -s localhost:8080/health
curl -s -X POST localhost:8080/v1/bootstrap | head
```

## Alternate deploy paths

1. **Console CD (what we used):** Cloud Run → Connect repository → Dockerfile `/Dockerfile` → branch `main`.
2. **Script:** `bash scripts/go_live_gcp.sh` with `GOOGLE_CLOUD_PROJECT` + ADC/SA key.
3. **Terraform:** after image push, apply with `-var="image=..."`.

## ADK web vs API

- **Local demos:** `adk web` (full multi-agent UI)
- **Cloud Run (default):** HTTP API above — `FINANCE_OPS_SERVE_MODE=http`
- **Same image, ADK surface:** set `FINANCE_OPS_SERVE_MODE=adk` → `adk api_server` via `deploy/entrypoint.sh`
- **Managed Agent Engine:** `bash scripts/go_live_agent_engine.sh` (see [parking-lot-go-live.md](parking-lot-go-live.md))
