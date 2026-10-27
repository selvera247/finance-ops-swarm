# GUI Connector + Portal Extract Contract

Enterprise portals without APIs are unlocked by a **narrow GUI agent**. Extracted
files land in a drop zone, then ingest into a **canonical** warehouse table that
insurance (SageSure-like) and medical billing (payer) portals share.

```text
Portal UI (mock bank / SageSure / Availity-like)
        │  Playwright (DOM) or future vision/SoM
        ▼
 data/incoming/<portal_id>/*.csv
        │  process_incoming / portal_ingest
        ▼
 warehouse.portal_extracts   ← canonical
        │
        ├─ bank_statements   ← compat for bank CSV shape
        ▼
 finance_ops tools
   list_portal_extracts / process_portal_incoming / fetch_legacy_bank_statement
```

## Drop zones

| Folder | Demo extract type | Example keys |
| --- | --- | --- |
| `data/incoming/legacy_bank/` | `bank_statement` | statement_id, account_id, amount |
| `data/incoming/sagesure/` | `policy_status` | policy_id, status, premium |
| `data/incoming/payer_availity/` | `claim_status` / remittance | claim_id, paid_amount, trn |

## Run

```bash
# Full GUI path (mock bank)
PYTHONPATH=. python scripts/run_gui_connector.py

# Drain any queued CSVs (SageSure / payer samples included)
PYTHONPATH=. python scripts/process_incoming.py
PYTHONPATH=. python scripts/process_incoming.py --portal sagesure
```

## Design rules

1. GUI only extracts and files — it does not update systems of record.
2. Matching / exceptions stay in ADK agents (`needs_review`, evidence IDs).
3. `portal_extracts.payload_json` keeps the full raw row for flexible fields.
4. Start with mock/demo CSVs; swap in real portal credentials later via secrets.
