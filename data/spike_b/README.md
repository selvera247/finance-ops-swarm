# Spike B — payer portal extract (Availity-shaped)

Scrubbed **claim / remittance exception** CSV for the `payer_availity` drop zone.
Ingests into canonical `portal_extracts` (same path as live portal watcher).

| File | Rows |
| --- | --- |
| `remittance_exceptions.csv` | 8 claim/ERA lines |

## Live walkthrough (3)

| Claim | Story |
| --- | --- |
| `CLM-B1001` | Clean paid ERA → remittance cites `INV-84219` (pairs with Spike A) |
| `CLM-B2001` | Denied CO-50 → HITL escalate / appeal |
| `CLM-B3001` | Orphan paid cash → no open claim |

## Load local warehouse

```powershell
$env:PYTHONPATH = (Get-Location).Path
python scripts\load_spike_b.py
```

Then:

```powershell
python -c "from finance_ops.tools.gui_tools import list_portal_extracts; import json; print(json.dumps(list_portal_extracts('payer_availity'), indent=2)[:2000])"
```

Agent tools: `process_portal_incoming`, `list_portal_extracts`, `request_portal_extract_review`, `shadow_spike_b_walkthrough`.
