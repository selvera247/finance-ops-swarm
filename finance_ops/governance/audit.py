"""Append-only governance audit log (JSONL + optional BigQuery ship)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_plane.config import WAREHOUSE_DIR, ensure_dirs

_AUDIT_REL = Path("governance") / "audit.jsonl"


def audit_path() -> Path:
    ensure_dirs()
    root = WAREHOUSE_DIR / "governance"
    root.mkdir(parents=True, exist_ok=True)
    return WAREHOUSE_DIR / _AUDIT_REL


def args_hash(args: dict[str, Any] | None) -> str:
    raw = json.dumps(args or {}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def append_audit(
    *,
    event: str,
    agent: str,
    decision: str,
    tool: str | None = None,
    args: dict[str, Any] | None = None,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one structured audit record. Local JSONL always; BQ when enabled.

    BQ ship failures are recorded on the return dict and never raise — local
    append remains the process-local source of truth for demos.
    """
    record: dict[str, Any] = {
        "event_id": f"AUD-{uuid.uuid4().hex[:12]}",
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "agent": agent,
        "tool": tool,
        "args_hash": args_hash(args),
        "decision": decision,
        "reason": reason,
    }
    if extra:
        try:
            from finance_ops.runtime.sanitize import sanitize_for_export

            record["extra"] = sanitize_for_export(extra)
        except Exception:  # noqa: BLE001
            record["extra"] = extra
    if args:
        try:
            from finance_ops.runtime.sanitize import sanitize_for_export

            record["args_safe"] = sanitize_for_export(args)
        except Exception:  # noqa: BLE001
            pass
    try:
        path = audit_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except OSError:
        record["audit_write_error"] = True

    try:
        from finance_ops.governance.audit_bq import ship_audit_record

        ship = ship_audit_record(record)
        if ship.get("shipped"):
            record["bq"] = {"shipped": True, "event_id": ship.get("event_id")}
        elif not ship.get("skipped"):
            record["bq"] = {"shipped": False, "error": ship.get("error") or ship}
    except Exception as exc:  # noqa: BLE001
        record["bq"] = {"shipped": False, "error": str(exc)}

    return record
