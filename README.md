# Finance Ops Swarm

**Public skeleton of a real finance agent swarm** — not a chatbot on PDFs.

Coordinator routes. Specialists own lanes. Policy can say no. Humans only move money.

```text
Cloud Run → BigQuery → durable jobs
                ↓
         coordinator (no cash apply)
         ├ invoice    ├ payments
         ├ contracts  └ reconciliation
                ↓
         policy → Slack HITL → audit
         HubSpot read / webhook → WF-HS-DEAL-{id}
```

This repo is the **true architecture skeleton** behind the Meridian narrative: governed Data → AI on BigQuery, with HubSpot as CRM context, RBAC, evidence, durable resume, and evals. Private demo history and warehouse artifacts stay out; the code paths are the same ones that ran in the private build.

## What is real here

| Layer | In this skeleton |
| --- | --- |
| Swarm | ADK coordinator + invoice / payments / contracts / reconciliation |
| Data | BigQuery mode (+ local warehouse for offline demos) |
| CRM | HubSpot read tools, sold-vs-contracted compare, aging enrich, company match |
| Governance | Deny-by-default RBAC, policy-as-code, audit (+ optional BQ ship), registry sweep |
| Runtime | Fallback router, circuit breaker, durable DAG, Slack HITL, shadow trajectories |
| Safety | Sanitize (email/phone/injection), sandbox calc, trajectory evals in CI |
| Cloud | FastAPI on Cloud Run (`finance_ops/serving.py`) · `POST /v1/hubspot/webhook` |

**Hard rule:** the coordinator cannot apply cash. HubSpot writes are HITL/runtime-only and soft-fail. Duplicates never auto-merge.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium

cp finance_ops/.env.example finance_ops/.env
# GOOGLE_API_KEY for live agents
# HUBSPOT_ACCESS_TOKEN / HUBSPOT_CLIENT_SECRET when wiring CRM
# FINANCE_OPS_DATA_MODE=bigquery + GOOGLE_CLOUD_PROJECT for BQ

PYTHONPATH=. pytest -q
PYTHONPATH=. python evals/run_trajectory_eval.py --dry-run
PYTHONPATH=. python scripts/run_e2e_data_to_ai.py
```

## Layout

```text
finance_ops/          agents, tools, governance, runtime, HubSpot, serving
data_plane/           repository, features, vectors, graph, BQ adapter
pipelines/            batch + stream
gui_connectors/       mock portal + Playwright when there is no API
evals/                trajectory cases (RBAC + HubSpot injection)
docs/                 architecture, go-live, swarm narrative
tests/                unit gates
```

## Trust ladder (do not skip)

1. **Read** — warehouse / HubSpot context, evidence cited  
2. **Suggest** — matches and gaps, shadow trajectories  
3. **Approve** — policy → Slack HITL  
4. **Apply** — payments agent only, after human gate  

## Docs

- [Swarm narrative](docs/swarm-narrative.md) — Meridian story (provocative, BigQuery-native)
- [CFO/CTO one-pager](docs/cfo-cto-one-pager.md)
- [Architecture](docs/architecture.md)
- [HubSpot notes](README.md#hubspot) · webhook + scopes in `finance_ops/.env.example`

## HubSpot

Private-app token via env only. Never commit tokens.

| Who | HubSpot |
| --- | --- |
| invoice / contracts / reconciliation | Read (+ scoped composites) |
| coordinator / payments | Neither |
| HITL runtime | `create_task` / `create_note` (soft-fail) |

Webhook: `POST /v1/hubspot/webhook` — v3 signature, 5-minute replay window, durable `WF-HS-DEAL-{id}`.

## License / status

Public architecture skeleton for portfolio and review. Treat secrets, live customer data, and production HubSpot/GCP projects as out of band — use `.env.example` only in git.
