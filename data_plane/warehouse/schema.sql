CREATE TABLE IF NOT EXISTS invoices (
  invoice_id VARCHAR PRIMARY KEY,
  customer_id VARCHAR,
  customer_name VARCHAR,
  contract_id VARCHAR,
  amount DOUBLE,
  currency VARCHAR,
  issue_date DATE,
  due_date DATE,
  status VARCHAR,
  aging_bucket VARCHAR,
  po_number VARCHAR,
  ingested_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
  payment_id VARCHAR PRIMARY KEY,
  customer_id VARCHAR,
  amount DOUBLE,
  currency VARCHAR,
  payment_date DATE,
  method VARCHAR,
  reference VARCHAR,
  matched_invoice_id VARCHAR,
  status VARCHAR,
  ingested_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contracts (
  contract_id VARCHAR PRIMARY KEY,
  customer_id VARCHAR,
  customer_name VARCHAR,
  effective_date DATE,
  end_date DATE,
  payment_terms VARCHAR,
  currency VARCHAR,
  credit_limit DOUBLE,
  sla_notes VARCHAR,
  status VARCHAR,
  ingested_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kg_nodes (
  id VARCHAR PRIMARY KEY,
  type VARCHAR,
  label VARCHAR
);

CREATE TABLE IF NOT EXISTS kg_edges (
  source VARCHAR,
  target VARCHAR,
  type VARCHAR
);

CREATE TABLE IF NOT EXISTS policy_docs (
  doc_id VARCHAR PRIMARY KEY,
  title VARCHAR,
  text VARCHAR,
  ingested_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stream_events (
  event_id VARCHAR PRIMARY KEY,
  event_type VARCHAR,
  payload_json VARCHAR,
  event_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customer_features (
  customer_id VARCHAR PRIMARY KEY,
  open_invoice_count INTEGER,
  open_ar_amount DOUBLE,
  past_due_amount DOUBLE,
  unmatched_payment_count INTEGER,
  credit_limit DOUBLE,
  utilization DOUBLE,
  risk_band VARCHAR,
  computed_at TIMESTAMP
);

-- Legacy compatibility table (still filled for bank CSV shape)
CREATE TABLE IF NOT EXISTS bank_statements (
  statement_id VARCHAR,
  account_id VARCHAR,
  txn_date DATE,
  description VARCHAR,
  amount DOUBLE,
  currency VARCHAR,
  source_file VARCHAR,
  ingested_at TIMESTAMP
);

-- Canonical multi-portal extract contract (bank, SageSure-like, payer, etc.)
CREATE TABLE IF NOT EXISTS portal_extracts (
  extract_id VARCHAR PRIMARY KEY,
  portal_id VARCHAR,
  extract_type VARCHAR,
  external_id VARCHAR,
  entity_id VARCHAR,
  txn_date DATE,
  amount DOUBLE,
  currency VARCHAR,
  description VARCHAR,
  status VARCHAR,
  payload_json VARCHAR,
  source_file VARCHAR,
  batch_id VARCHAR,
  ingested_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  run_id VARCHAR PRIMARY KEY,
  stage VARCHAR,
  status VARCHAR,
  detail VARCHAR,
  started_at TIMESTAMP,
  finished_at TIMESTAMP
);
