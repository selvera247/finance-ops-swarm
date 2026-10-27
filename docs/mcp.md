# Read-only MCP (C1)

Exposes finance warehouse tools to MCP clients (Cursor, Claude Desktop) **without**
ADK and **without** write/HITL/apply tools.

## Tools

| Tool | Purpose |
| --- | --- |
| `aging_summary` | Open AR by customer |
| `list_open_invoices` | Open/past_due invoices |
| `lookup_invoice` | One invoice |
| `list_unmatched_payments` | Cash exception queue |
| `lookup_payment` | One payment |
| `suggest_payment_match` | Match **suggestion** only (no apply) |
| `search_policies` | Policy RAG |
| `get_evidence` / `recent_evidence` | Audit trail |
| `bigquery_status` | Data plane status |
| `graph_neighborhood` | KG read |

**Not exposed:** `apply_payment_match`, `request_cash_app_approval`, `decide_approval`, GUI browser pulls, durable workflows.

## Run locally

```powershell
cd C:\Users\Selvera\finance_agents
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = (Get-Location).Path
python scripts\load_spike_a.py   # optional Spike A data
python -m finance_ops.mcp        # stdio — used by Cursor MCP config
```

## Cursor MCP config

Add to Cursor MCP settings (or project `.cursor/mcp.json` if your Cursor build supports it).
Adjust the absolute path to your clone:

```json
{
  "mcpServers": {
    "finance_ops_readonly": {
      "command": "C:\\Users\\Selvera\\finance_agents\\.venv\\Scripts\\python.exe",
      "args": ["-m", "finance_ops.mcp"],
      "cwd": "C:\\Users\\Selvera\\finance_agents",
      "env": {
        "PYTHONPATH": "C:\\Users\\Selvera\\finance_agents",
        "FINANCE_OPS_DATA_MODE": "warehouse"
      }
    }
  }
}
```

On macOS/Linux use `.venv/bin/python` and forward-slash paths.

## Try in Cursor

After the server is connected:

- “Call aging_summary for CUST-ACME”
- “List unmatched payments for C-1042”
- “Suggest payment match for PAY-2001” (suggest only — approve still via ADK/HITL)

## Relation to Cloud Run / ADK

| Surface | Role |
| --- | --- |
| ADK agents | Full tools + HITL writes |
| Cloud Run `/v1/*` | HTTP API for apps/scripts |
| MCP (this) | IDE / external AI **read** gateway |
