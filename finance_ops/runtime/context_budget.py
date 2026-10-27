"""C4 — pack tool/memory payloads to fit a context budget.

Prefers summaries + ids over full row dumps. Does not mutate warehouse state.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

PackKind = Literal["payments", "invoices", "memory", "generic", "auto"]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return max(1, int(raw)) if raw else default
    except ValueError:
        return default


def budget_limits() -> dict[str, int]:
    return {
        "max_items": _env_int("FINANCE_OPS_CTX_MAX_ITEMS", 8),
        "max_chars": _env_int("FINANCE_OPS_CTX_MAX_CHARS", 4000),
        "max_str": _env_int("FINANCE_OPS_CTX_MAX_STR", 240),
    }


def _clip_str(s: str, max_str: int) -> str:
    if len(s) <= max_str:
        return s
    return s[: max_str - 1] + "…"


def _trim_value(value: Any, max_str: int, depth: int = 0) -> Any:
    if depth > 6:
        return "…"
    if isinstance(value, str):
        return _clip_str(value, max_str)
    if isinstance(value, dict):
        return {k: _trim_value(v, max_str, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_trim_value(v, max_str, depth + 1) for v in value[:40]]
    return value


def _payment_row(row: dict[str, Any], max_str: int) -> dict[str, Any]:
    keep = (
        "payment_id",
        "customer_id",
        "amount",
        "currency",
        "status",
        "reference",
        "matched_invoice_id",
        "method",
    )
    return {k: _trim_value(row.get(k), max_str) for k in keep if k in row}


def _invoice_row(row: dict[str, Any], max_str: int) -> dict[str, Any]:
    keep = (
        "invoice_id",
        "customer_id",
        "amount",
        "currency",
        "status",
        "due_date",
        "po_number",
    )
    return {k: _trim_value(row.get(k), max_str) for k in keep if k in row}


def _memory_row(row: dict[str, Any], max_str: int) -> dict[str, Any]:
    keep = ("memory_id", "tier", "key", "session_id", "tags", "pinned", "value", "last_accessed_at")
    return {k: _trim_value(row.get(k), max_str) for k in keep if k in row}


def _detect_kind(payload: Any) -> PackKind:
    if isinstance(payload, dict):
        if isinstance(payload.get("payments"), list):
            return "payments"
        if isinstance(payload.get("invoices"), list):
            return "invoices"
        if isinstance(payload.get("items"), list) and payload.get("items"):
            first = payload["items"][0]
            if isinstance(first, dict) and "tier" in first and "key" in first:
                return "memory"
        if isinstance(payload.get("trajectories"), list):
            return "generic"
    return "generic"


def pack_context(
    payload: Any,
    *,
    kind: PackKind = "auto",
    max_items: int | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Return a budgeted view of ``payload`` suitable for model context."""
    limits = budget_limits()
    max_items = max_items or limits["max_items"]
    max_chars = max_chars or limits["max_chars"]
    max_str = limits["max_str"]
    resolved: PackKind = _detect_kind(payload) if kind == "auto" else kind

    omitted = 0
    packed: Any
    summary: dict[str, Any] = {}

    if resolved == "payments" and isinstance(payload, dict):
        rows = list(payload.get("payments") or [])
        kept = [_payment_row(r, max_str) for r in rows[:max_items] if isinstance(r, dict)]
        omitted = max(0, len(rows) - len(kept))
        packed = {**{k: v for k, v in payload.items() if k != "payments"}, "payments": kept, "count": len(kept)}
        summary = {
            "total": len(rows),
            "shown": len(kept),
            "statuses": _count_by(rows, "status"),
        }
    elif resolved == "invoices" and isinstance(payload, dict):
        rows = list(payload.get("invoices") or [])
        kept = [_invoice_row(r, max_str) for r in rows[:max_items] if isinstance(r, dict)]
        omitted = max(0, len(rows) - len(kept))
        packed = {**{k: v for k, v in payload.items() if k != "invoices"}, "invoices": kept, "count": len(kept)}
        summary = {"total": len(rows), "shown": len(kept)}
    elif resolved == "memory" and isinstance(payload, dict):
        rows = list(payload.get("items") or [])
        kept = [_memory_row(r, max_str) for r in rows[:max_items] if isinstance(r, dict)]
        omitted = max(0, len(rows) - len(kept))
        packed = {**{k: v for k, v in payload.items() if k != "items"}, "items": kept, "count": len(kept)}
        summary = {"total": len(rows), "shown": len(kept)}
    else:
        packed = _trim_value(payload, max_str)
        if isinstance(packed, list) and len(packed) > max_items:
            omitted = len(packed) - max_items
            packed = packed[:max_items]
        summary = {"kind": "generic"}

    text = json.dumps(packed, default=str)
    truncated_chars = False
    if len(text) > max_chars:
        truncated_chars = True
        # Progressive shrink of list-like fields
        if isinstance(packed, dict):
            for list_key in ("payments", "invoices", "items", "candidates", "trajectories"):
                if isinstance(packed.get(list_key), list) and packed[list_key]:
                    while len(json.dumps(packed, default=str)) > max_chars and len(packed[list_key]) > 1:
                        packed[list_key].pop()
                        omitted += 1
                    packed["count"] = len(packed[list_key])
        text = json.dumps(packed, default=str)
        if len(text) > max_chars:
            packed = {
                "truncated": True,
                "preview": text[: max_chars - 20] + "…",
                "original_chars": len(text),
            }
            text = json.dumps(packed, default=str)

    return {
        "status": "success",
        "kind": resolved,
        "budget": {
            "max_items": max_items,
            "max_chars": max_chars,
            "chars": len(text),
            "omitted_items": omitted,
            "truncated_chars": truncated_chars,
        },
        "summary": summary,
        "packed": packed,
        "needs_review": False,
    }


def _count_by(rows: list[Any], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        k = str(row.get(key) or "unknown")
        out[k] = out.get(k, 0) + 1
    return out
