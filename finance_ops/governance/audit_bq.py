"""Ship governance audit records to BigQuery (append-only, opt-in).

Enable with FINANCE_OPS_AUDIT_BQ=true and GOOGLE_CLOUD_PROJECT.
Agents keep writing local JSONL; BQ is the durable copy agents should not own.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from data_plane.config import bigquery_dataset, gcp_project


def audit_bq_enabled() -> bool:
    return os.getenv("FINANCE_OPS_AUDIT_BQ", "").strip().lower() in {"1", "true", "yes"}


def _table_id(project: str, dataset: str) -> str:
    return f"{project}.{dataset}.governance_audit"


def ensure_audit_table(client: Any, project: str, dataset: str) -> None:
    """Create governance_audit if missing (idempotent)."""
    ddl = f"""
    CREATE TABLE IF NOT EXISTS `{project}.{dataset}.governance_audit` (
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
    )
    """
    client.query(ddl).result()


def record_to_bq_row(record: dict[str, Any]) -> dict[str, Any]:
    extra = record.get("extra")
    ts_raw = record.get("ts")
    # BigQuery accepts ISO8601 strings for TIMESTAMP on insert_rows_json
    return {
        "event_id": record.get("event_id") or f"AUD-{uuid.uuid4().hex[:12]}",
        "ts": ts_raw,
        "event": record.get("event"),
        "agent": record.get("agent"),
        "tool": record.get("tool"),
        "args_hash": record.get("args_hash"),
        "decision": record.get("decision"),
        "reason": record.get("reason"),
        "extra_json": json.dumps(extra, default=str) if extra is not None else None,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def ship_audit_record(record: dict[str, Any]) -> dict[str, Any]:
    """Insert one audit row into BigQuery. No-op when disabled. Never raises to callers."""
    if not audit_bq_enabled():
        return {"shipped": False, "skipped": True, "reason": "disabled"}
    project = gcp_project() or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        return {"shipped": False, "error": "GOOGLE_CLOUD_PROJECT required"}
    dataset = bigquery_dataset()
    try:
        from google.cloud import bigquery
    except ImportError:
        return {"shipped": False, "error": "google-cloud-bigquery not installed"}
    try:
        client = bigquery.Client(project=project)
        ensure_audit_table(client, project, dataset)
        row = record_to_bq_row(record)
        errors = client.insert_rows_json(_table_id(project, dataset), [row])
        if errors:
            return {"shipped": False, "error": "insert_errors", "details": errors}
        return {
            "shipped": True,
            "event_id": row["event_id"],
            "table": _table_id(project, dataset),
        }
    except Exception as exc:  # noqa: BLE001 — best-effort ship
        return {"shipped": False, "error": str(exc)}


def ship_audit_jsonl(path: Any | None = None, *, limit: int | None = None) -> dict[str, Any]:
    """Backfill local JSONL lines to BigQuery (CLI / ops)."""
    from finance_ops.governance.audit import audit_path

    if not audit_bq_enabled():
        return {"status": "skipped", "reason": "FINANCE_OPS_AUDIT_BQ not enabled"}
    target = path or audit_path()
    if not target.is_file():
        return {"status": "error", "error": f"missing {target}", "shipped": 0}
    shipped = 0
    failed = 0
    errors: list[Any] = []
    with target.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if limit is not None and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                failed += 1
                errors.append({"line": i + 1, "error": str(exc)})
                continue
            result = ship_audit_record(record)
            if result.get("shipped"):
                shipped += 1
            else:
                failed += 1
                errors.append({"line": i + 1, "result": result})
    return {
        "status": "success" if failed == 0 else "partial",
        "shipped": shipped,
        "failed": failed,
        "errors": errors[:20],
    }
