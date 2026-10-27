# Portal incoming drop zones

GUI agents (or humans) drop export files here. The watcher ingests them into
`warehouse.portal_extracts` and moves files to `<portal>/processed/`.

```text
data/incoming/
  legacy_bank/       # mock bank / statement CSVs
  sagesure/          # policy/commission status exports (demo)
  payer_availity/    # claim status / remittance exports (demo)
  <portal>/processed/
```

Run:

```bash
PYTHONPATH=. python scripts/process_incoming.py
PYTHONPATH=. python scripts/process_incoming.py --portal sagesure
```

Canonical table: `portal_extracts` (`portal_id`, `extract_type`, `external_id`, …).
