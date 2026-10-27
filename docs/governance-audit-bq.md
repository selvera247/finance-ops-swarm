# Governance audit → BigQuery

Local process writes append-only JSONL to `.warehouse/governance/audit.jsonl`.
When enabled, each event is also inserted into BigQuery for durable, agent-hostile storage.

## Enable

```text
FINANCE_OPS_AUDIT_BQ=true
GOOGLE_CLOUD_PROJECT=gen-lang-client-0611250410
FINANCE_OPS_BQ_DATASET=finance_ops
```

Table DDL is in `data_plane/warehouse/bq_schema.sql` (`governance_audit`).
The shipper also runs `CREATE TABLE IF NOT EXISTS` on first insert.

## IAM (recommended)

Grant the Cloud Run / loader service account **BigQuery Data Editor** only on
`governance_audit` (or dataset-level insert). Prefer **no** `UPDATE` / `DELETE`
on that table so runtime compromise cannot rewrite history.

## Ops

```powershell
# live ship on every append_audit (when env enabled)
# backfill existing JSONL:
$env:FINANCE_OPS_AUDIT_BQ = "true"
python -m finance_ops.governance.cli ship-audit
```

## Verify

```sql
SELECT event, agent, decision, reason, ts
FROM `PROJECT.finance_ops.governance_audit`
ORDER BY ts DESC
LIMIT 50
```
