-- Spanner Graph–shaped relational schema (property graph via tables).
-- Apply: bash scripts/go_live_spanner.sh
--   or: gcloud spanner databases ddl update ... --ddl-file=...

CREATE TABLE kg_nodes (
  id STRING(128) NOT NULL,
  type STRING(64),
  label STRING(256),
) PRIMARY KEY (id);

CREATE TABLE kg_edges (
  edge_id STRING(128) NOT NULL,
  source STRING(128) NOT NULL,
  target STRING(128) NOT NULL,
  type STRING(64),
) PRIMARY KEY (edge_id);
