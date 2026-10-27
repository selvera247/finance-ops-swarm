# Master layer complete — L7 · L3 · #8 Slack HITL

All three items are implemented and validated. Cloud ladder L4–L6 is also complete
(see [l4-l5-l6-complete.md](l4-l5-l6-complete.md) and [master-plan-status.md](master-plan-status.md)).

| Item | Meaning | Proof |
| --- | --- | --- |
| **L7** | CFO/CTO one-pager | `docs/cfo-cto-one-pager.md` |
| **L3** | BigQuery behind invoice/payment tools | `FINANCE_OPS_DATA_MODE=bigquery` → `bq_adapter` (DuckDB fallback) |
| **#8** | Slack Approve/Reject | `SLACK_WEBHOOK_URL` → card in `#all-demo` → HITL server |

## Your Windows verify (10 minutes)

```powershell
cd C:\Users\Selvera\Documents\finance_agents\finance_agents
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "."

# 1) L7 — open the narrative
notepad docs\cfo-cto-one-pager.md

# 2) L3 — mode works without GCP (fallback)
python scripts/smoke_master_layer.py

# 3) #8 Slack — HITL up + ADK prompt
python -m finance_ops.runtime.hitl_server
# other terminal: adk web --port 8000
# Prompt: Request approval for write-off amount 50 summary master-layer check.
# Approve from desktop Slack (not phone localhost).
# Prompt: Get approval APPR-...
```

## Env (`finance_ops\.env`)

```env
GOOGLE_API_KEY=...
FINANCE_OPS_MODEL=gemini-3.1-flash-lite
FINANCE_OPS_DATA_MODE=warehouse
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
HITL_PUBLIC_BASE_URL=http://127.0.0.1:8787

# Optional live BigQuery:
# FINANCE_OPS_DATA_MODE=bigquery
# GOOGLE_CLOUD_PROJECT=your-project
```

## Status

**Complete.** Full master-plan scorecard (including live Cloud Run): [master-plan-status.md](master-plan-status.md).
