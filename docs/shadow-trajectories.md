# C3 — Shadow trajectories

Record the cash-app (or other) tool path the agent **would** take **without**
creating HITL approvals, sending Slack, or applying matches.

## Why

- Demo Spike A safely (PAY-1001 / 2001 / 3001) without changing DuckDB  
- Compare “proposed apply” vs live HITL later  
- Audit what would mutate (`would_mutate`, `side_effect=shadow_skipped`)

## Tools

| Tool | Behavior |
| --- | --- |
| `shadow_cash_app_trajectory(payment_id, invoice_id="")` | Runs `suggest_payment_match` (read); proposes HITL + apply |
| `shadow_spike_a_walkthrough()` | Shadows the three walkthrough payments |
| `list_shadow_trajectories` / `get_shadow_trajectory` | Inspect stored `SHD-*` JSON |

Persisted under `.warehouse/shadow/`.

## Step shape

```json
{
  "tool": "apply_payment_match",
  "side_effect": "shadow_skipped",
  "status": "proposed",
  "outputs": { "predict": { "ok": true, "would_set": { "status": "matched" } } }
}
```

`side_effect=read_ok` means a real read ran. `shadow_skipped` means a write was
**not** executed.

## Vs live path

| Shadow | Live |
| --- | --- |
| `shadow_cash_app_trajectory` | `request_cash_app_approval` → HITL → apply |
| `mutated: false` always | Warehouse + approval store change |

## Not in MCP

Read-only MCP stays warehouse reads. Shadow is an ADK agent tool (still non-mutating).
