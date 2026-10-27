# 3) Managed graph — Neo4j Aura (recommended) or Spanner Graph tables

## Option A — Neo4j Aura (managed Cypher)

1. Create free instance: https://console.neo4j.io  
2. Copy **Query API / Bolt URI**, username, password.  
3. Sync data (from a machine with network to Aura):

```bash
export FINANCE_OPS_GRAPH_BACKEND=neo4j
export NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
export NEO4J_USER=neo4j
export NEO4J_PASSWORD='...'
pip install neo4j
PYTHONPATH=. python scripts/sync_knowledge_graph.py --backend neo4j --export
```

4. Cloud Run → **Edit & deploy** → Variables:

```text
FINANCE_OPS_GRAPH_BACKEND=neo4j
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=***
```

Prefer Secret Manager for the password in production.

5. Confirm: `GET /v1/status` → `graph.backend=neo4j`, `graph.ok=true`.

## Option B — Spanner Graph–shaped tables

1. Enable Spanner API; create instance + database.  
2. Apply DDL: `data_plane/graph/spanner_schema.sql`  
3. Set on Cloud Run:

```text
FINANCE_OPS_GRAPH_BACKEND=spanner
SPANNER_INSTANCE=finance-ops
SPANNER_DATABASE=finance_ops
GOOGLE_CLOUD_PROJECT=gen-lang-client-0611250410
```

4. Or run the automated path:

```bash
export GOOGLE_CLOUD_PROJECT=gen-lang-client-0611250410
bash scripts/go_live_spanner.sh
```

**Default live today:** sqlite/duckdb via `/v1/bootstrap` (already working on Cloud Run).
