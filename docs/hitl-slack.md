# HITL → Slack (#8) — complete

Local approval store is the source of truth. Slack is notify + Approve/Reject.

## Env (`finance_ops\.env`)

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
HITL_PUBLIC_BASE_URL=http://127.0.0.1:8787
```

Create webhook: https://api.slack.com/apps → your app → **Incoming Webhooks** → On → Add to channel.

## Run

```powershell
$env:PYTHONPATH = "."
python -m finance_ops.runtime.hitl_server
# ADK: Request approval for write-off amount 125 summary Slack test INV-1001.
```

## Approve correctly

| Client | Works? |
| --- | --- |
| **Desktop Slack** on same PC as `hitl_server` | Yes — link hits `127.0.0.1:8787` |
| **Phone Slack** with localhost URL | No — phone ≠ your PC |
| Phone later | Run ngrok → set `HITL_PUBLIC_BASE_URL=https://….ngrok.io` |

After Approve, in ADK:

```text
Get approval APPR-...
```

Expect `status: approved`, `decided_by: hitl_web`.

## Endpoints

| Path | Purpose |
| --- | --- |
| `GET /approvals` | Local list UI |
| `GET /approve?id=&token=` | Slack link target |
| `POST /api/decide` | Programmatic resume |
| `POST /slack/interactions` | Interactive payload (`id:token:decision`) |
| `GET /api/approval/<id>` | Status by id |

## Agent tools

- `request_approval` — creates `APPR-…` + `notify_slack`
- `get_approval` / `list_pending_approvals` / `decide_approval`
