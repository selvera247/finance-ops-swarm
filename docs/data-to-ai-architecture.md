# End-to-end Data → AI Architecture

```text
 Sources (ERP/JSON) + Legacy / carrier / payer portals
        │
        ├─ batch ingest ────────────────────┐
        ├─ GUI connector (Playwright) ──────┤
        │      ↓                            │
        │  data/incoming/<portal>/          │
        │      ↓ portal_ingest              ▼
        │                         Warehouse (DuckDB / BigQuery)
 Pub/Sub stand-in ──► stream_events         │
                                            ├─ Features
                                            ├─ Knowledge graph
                                            ├─ Vectors / RAG
                                            ├─ portal_extracts (canonical)
                                            ├─ bank_statements (compat)
                                            ▼
                                   ADK multi-agent finance_ops
                                            ▼
                                   Evidence / AgentOps
```

See `docs/gui-connector.md` for the multi-portal extract contract.
