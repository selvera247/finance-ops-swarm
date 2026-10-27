"""Agent tools for C4 context budget, C5 sanitize, C6 self-heal."""

from __future__ import annotations

import json
from typing import Any

from finance_ops.lib.evidence import record_evidence
from finance_ops.runtime.circuit_breaker import DEFAULT_BREAKER
from finance_ops.runtime.context_budget import pack_context
from finance_ops.runtime.sanitize import sanitize_for_export
from finance_ops.runtime.self_heal import heal_result, run_with_heal


def _guard(name: str) -> None:
    DEFAULT_BREAKER.record_tool(name)


def budget_pack_context(
    payload_json: str,
    kind: str = "auto",
    max_items: int = 0,
    max_chars: int = 0,
) -> dict[str, Any]:
    """C4: Pack a JSON tool result for model context (top-N + char cap).

    kind: auto | payments | invoices | memory | generic
    """
    _guard("budget_pack_context")
    try:
        payload = json.loads(payload_json) if payload_json.strip() else {}
    except json.JSONDecodeError as exc:
        result: dict[str, Any] = {
            "status": "error",
            "error": f"invalid payload_json: {exc}",
            "needs_review": True,
        }
        result["evidence"] = record_evidence(
            agent="coordinator",
            action="budget_pack_context",
            inputs={"kind": kind},
            outputs=result,
            sources=["craft:c4"],
        )
        return result

    packed = pack_context(
        payload,
        kind=kind if kind in {"auto", "payments", "invoices", "memory", "generic"} else "auto",  # type: ignore[arg-type]
        max_items=int(max_items) or None,
        max_chars=int(max_chars) or None,
    )
    packed["evidence"] = record_evidence(
        agent="coordinator",
        action="budget_pack_context",
        inputs={"kind": kind, "max_items": max_items or None, "max_chars": max_chars or None},
        outputs={
            "kind": packed.get("kind"),
            "budget": packed.get("budget"),
            "summary": packed.get("summary"),
        },
        sources=["craft:c4"],
    )
    return packed


def sanitize_payload(payload_json: str) -> dict[str, Any]:
    """C5: Redact secrets/PII-shaped values from a JSON payload (preview only)."""
    _guard("sanitize_payload")
    try:
        payload = json.loads(payload_json) if payload_json.strip() else {}
    except json.JSONDecodeError:
        payload = payload_json
    cleaned = sanitize_for_export(payload)
    result = {
        "status": "success",
        "sanitized": cleaned,
        "needs_review": False,
    }
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="sanitize_payload",
        inputs={"chars": len(payload_json or "")},
        outputs={"status": "success"},
        sources=["craft:c5"],
    )
    return result


def heal_tool_result(
    tool: str,
    result_json: str = "",
    error: str = "",
) -> dict[str, Any]:
    """C6: Classify a failed tool result and return heal steps (no auto side effects).

    For live retry with a known tool, prefer ``heal_suggest_payment`` / specialists.
    """
    _guard("heal_tool_result")
    result: dict[str, Any] | None = None
    if result_json.strip():
        try:
            parsed = json.loads(result_json)
            if isinstance(parsed, dict):
                result = parsed
        except json.JSONDecodeError:
            result = {"status": "error", "error": "invalid result_json"}
    out = heal_result(tool=tool or "unknown", result=result, error=error or None, retry_fn=None)
    out["evidence"] = record_evidence(
        agent="coordinator",
        action="heal_tool_result",
        inputs={"tool": tool, "error": error or None},
        outputs={
            "status": out.get("status"),
            "classification": out.get("classification"),
            "healed": out.get("healed"),
            "steps": len(out.get("heal_steps") or []),
        },
        sources=["craft:c6"],
    )
    return out


def heal_suggest_payment(payment_id: str) -> dict[str, Any]:
    """C6: Run suggest_payment_match with one heal retry on transient/circuit failure."""
    _guard("heal_suggest_payment")
    from finance_ops.tools.payment_tools import suggest_payment_match

    pid = payment_id.strip().upper()

    def _call() -> dict[str, Any]:
        return suggest_payment_match(pid)

    out = run_with_heal("suggest_payment_match", _call)
    out["evidence"] = record_evidence(
        agent="payments_agent",
        action="heal_suggest_payment",
        inputs={"payment_id": pid},
        outputs={
            "status": out.get("status"),
            "healed": out.get("healed"),
            "classification": out.get("classification"),
            "recommendation": (out.get("result") or {}).get("recommendation"),
        },
        sources=["craft:c6", "payments:suggest"],
    )
    return out
