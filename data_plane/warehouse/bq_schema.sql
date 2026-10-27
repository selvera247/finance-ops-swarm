-- BigQuery DDL for finance_ops dataset (L3). Apply after terraform dataset exists.
-- Example: bq query --use_legacy_sql=false < data_plane/warehouse/bq_schema.sql

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.invoices` (
  invoice_id STRING,
  customer_id STRING,
  amount FLOAT64,
  currency STRING,
  status STRING,
  aging_bucket STRING,
  due_date STRING,
  po_number STRING
);

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.payments` (
  payment_id STRING,
  customer_id STRING,
  amount FLOAT64,
  currency STRING,
  status STRING,
  reference STRING,
  received_at STRING,
  matched_invoice_id STRING
);

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.contracts` (
  contract_id STRING,
  customer_id STRING,
  payment_terms STRING,
  credit_limit FLOAT64,
  status STRING,
  sla_days INT64
);

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.portal_extracts` (
  extract_id STRING,
  portal_id STRING,
  extract_type STRING,
  external_id STRING,
  entity_id STRING,
  txn_date STRING,
  amount FLOAT64,
  currency STRING,
  description STRING,
  status STRING,
  raw_json STRING,
  source_file STRING,
  batch_id STRING,
  ingested_at TIMESTAMP
);

-- Append-only governance audit (shipped from finance_ops.governance.audit).
-- Prefer insert-only IAM for the runtime SA; agents should not UPDATE/DELETE.
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.governance_audit` (
  event_id STRING,
  ts TIMESTAMP,
  event STRING,
  agent STRING,
  tool STRING,
  args_hash STRING,
  decision STRING,
  reason STRING,
  extra_json STRING,
  ingested_at TIMESTAMP
);
