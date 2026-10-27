# BigQuery L3 — complete

Same agent tools. `repository` uses BigQuery when
`FINANCE_OPS_DATA_MODE=bigquery`; **`bq_adapter` falls back to DuckDB** if
project/ADC/client are missing.

## Env

```env
FINANCE_OPS_DATA_MODE=bigquery
GOOGLE_CLOUD_PROJECT=your-gcp-project
FINANCE_OPS_BQ_DATASET=finance_ops
```

```bash
gcloud auth application-default login
pip install google-cloud-bigquery
```

## Load path

```bash
# Plan only (no credentials required)
PYTHONPATH=. python scripts/load_bigquery_demo.py --dry-run
PYTHONPATH=. python scripts/load_bigquery_demo.py --print-ddl

# Live (needs project + tables)
# terraform apply in infra/terraform  OR create dataset manually
# Apply DDL from --print-ddl via bq query
PYTHONPATH=. python scripts/load_bigquery_demo.py
```

## Verify without GCP

```bash
PYTHONPATH=. python scripts/smoke_master_layer.py
# Expect l3_bigquery_fallback.ok = true (duckdb_fallback + aging 16700)
```

In ADK with mode=bigquery and no project: `bigquery_status` →
`active_source=duckdb_fallback`, `needs_review=true`. With live BQ:
`active_source=bigquery`, `bigquery.ok=true`.
