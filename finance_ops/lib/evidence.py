from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from finance_ops.lib.paths import ensure_evidence_dir
from finance_ops.runtime.sanitize import sanitize_for_export


def record_evidence(
    *,
    agent: str,
    action: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    sources: list[str],
) -> dict[str, Any]:
    evidence_id = f"EVD-{uuid.uuid4().hex[:12]}"
    safe_inputs = sanitize_for_export(inputs)
    safe_outputs = sanitize_for_export(outputs)
    record = {
        "evidence_id": evidence_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "action": action,
        "inputs": safe_inputs,
        "outputs": safe_outputs,
        "sources": sources,
        "governance": {
            "requires_human_review": bool(
                (outputs or {}).get("needs_review", False)
                if isinstance(outputs, dict)
                else False
            ),
            "citation_count": len(sources),
            "sanitized": True,
        },
    }
    path = ensure_evidence_dir() / f"{evidence_id}.json"
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return {
        "evidence_id": evidence_id,
        "path": str(path),
        "timestamp": record["timestamp"],
    }


def list_evidence(limit: int = 20) -> list[dict[str, Any]]:
    out_dir = ensure_evidence_dir()
    files = sorted(out_dir.glob("EVD-*.json"), reverse=True)
    return [json.loads(p.read_text(encoding="utf-8")) for p in files[:limit]]


def load_evidence(evidence_id: str) -> dict[str, Any] | None:
    path = ensure_evidence_dir() / f"{evidence_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
