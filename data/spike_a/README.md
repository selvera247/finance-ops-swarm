# Spike A — cash app matching sample

Scrubbed exception-queue style payments + open AR for demo matching.

| File | Rows |
| --- | --- |
| `payments.csv` | 13 (unmatched / partial) |
| `invoices.csv` | 9 open/past_due |

**Must-fix applied:** `PAY-4001` reference is `Remittance INV-77110`.

## 1) Load local DuckDB (wire / HITL)

```powershell
$env:PYTHONPATH = (Get-Location).Path
python scripts\load_spike_a.py
```

## 2) Load BigQuery (Cloud Run path)

Cloud Run uses `FINANCE_OPS_DATA_MODE=bigquery`. Push Spike A into the live dataset:

```powershell
$env:GOOGLE_CLOUD_PROJECT = "gen-lang-client-0611250410"
$env:PYTHONPATH = (Get-Location).Path
python scripts\load_spike_a.py --bigquery-only
```

Or both warehouse + BQ: `python scripts\load_spike_a.py --bigquery`

Then on Cloud Run (after image has `/v1/suggest_payment_match`):

```powershell
Invoke-RestMethod -Method POST `
  -Uri "https://finance-ops-301858971164.us-central1.run.app/v1/suggest_payment_match" `
  -ContentType "application/json" `
  -Body '{"payment_id":"PAY-1001"}' | ConvertTo-Json -Depth 6
```

## Wire: suggest → Slack/HITL → apply

```powershell
# HITL server (desktop Slack links need this)
python -m finance_ops.runtime.hitl_server

# In another shell — opens APPR-… + optional Slack
python -c "from finance_ops.tools.payment_tools import request_cash_app_approval; import json; print(json.dumps(request_cash_app_approval('PAY-1001'), indent=2))"

# Approve via Slack button, http://127.0.0.1:8787/, or:
python -c "from finance_ops.tools.runtime_tools import decide_approval; import json; print(json.dumps(decide_approval('APPR-...','approved',resume_token='...'), indent=2))"
```

On **approved** + kind `cash_app_match`, payment becomes `status=matched` + `matched_invoice_id` set.

| # | Payment | Story |
| --- | --- | --- |
| 1 | **PAY-1001** | Clean → INV-84219 → Approve applies |
| 2 | **PAY-2001** | Ambiguous amount → HITL picks invoice_id |
| 3 | **PAY-3001** | No AR → `cash_app_escalate` (reject/approve without apply) |

## Agent prompts

```text
Suggest payment match for PAY-1001 and cite evidence_id.
Request cash app approval for PAY-1001.
# after Slack Approve:
Get approval APPR-...
Lookup payment PAY-1001
```
