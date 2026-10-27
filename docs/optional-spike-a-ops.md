# Spike A optional ops — Slack `.env` + BigQuery load

## 1) Slack webhook (cash-app / portal HITL notify)

Edit `finance_ops/.env` (create from `.env.example` if missing):

```text
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
HITL_PUBLIC_BASE_URL=http://127.0.0.1:8787
```

In a **new** terminal (dotenv loads on notify):

```powershell
cd C:\Users\Selvera\finance_agents
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = (Get-Location).Path

# HITL server (Approve links)
python -m finance_ops.runtime.hitl_server

# Separate terminal — smoke notify
python -c "from finance_ops.tools.payment_tools import request_cash_app_approval; import json; print(json.dumps(request_cash_app_approval('PAY-1001', notify_slack=True), indent=2)[:2000])"
```

Expect `slack.sent: true`. If `false`, webhook URL missing/invalid.

## 2) BigQuery load (Cloud Run data plane)

Requires `gcloud auth login` (or ADC) and BigQuery API enabled.

```powershell
$env:GOOGLE_CLOUD_PROJECT = "gen-lang-client-0611250410"
$env:FINANCE_OPS_BQ_DATASET = "finance_ops"
$env:PYTHONPATH = (Get-Location).Path

python scripts\load_spike_a.py --bigquery-only
```

If payments fail with `no such field: received_at`, the loader adds that column
automatically on current `main`. Or migrate once:

```powershell
python -c "from google.cloud import bigquery; c=bigquery.Client(project='gen-lang-client-0611250410'); c.query('ALTER TABLE `gen-lang-client-0611250410.finance_ops.payments` ADD COLUMN IF NOT EXISTS received_at STRING').result(); print('ok')"
```

Then confirm:

```powershell
# local tool status
python -c "from finance_ops.tools.bigquery_tools import bigquery_status; import json; print(json.dumps(bigquery_status(), indent=2))"
```

Cloud Run already uses `FINANCE_OPS_DATA_MODE=bigquery` when configured — after BQ load, call suggest on the service if that route is deployed.
