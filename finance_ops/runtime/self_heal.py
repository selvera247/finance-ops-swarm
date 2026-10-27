"""C6 — self-heal policy for tool failures.

Retry once on transient errors; escalate to needs_review; never invent balances.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from finance_ops.runtime.circuit_breaker import DEFAULT_BREAKER, CircuitOpenError

HealFn = Callable[[], dict[str, Any]]

_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "temporarily",
    "unavailable",
    "connection",
    "reset by peer",
    "429",
    "503",
    "circuit open",
)


def classify_error(error: str | None, status: str | None = None) -> str:
    blob = f"{status or ''} {error or ''}".lower()
    if "circuit open" in blob or status == "circuit_open":
        return "circuit_open"
    if "not_found" in blob or status == "not_found":
        return "not_found"
    if "denied" in blob or status == "denied":
        return "denied"
    if any(m in blob for m in _TRANSIENT_MARKERS):
        return "transient"
    if status in {"error", "failed", "timeout"}:
        return "error"
    return "unknown"


def heal_result(
    *,
    tool: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    retry_fn: HealFn | None = None,
    reset_circuit: bool = True,
) -> dict[str, Any]:
    """Apply heal policy to a failed (or empty) tool result.

    Returns a structured envelope with ``heal_steps`` and never mutates warehouse
    unless ``retry_fn`` itself does (caller supplies that).
    """
    steps: list[dict[str, Any]] = []
    result = dict(result or {})
    status = str(result.get("status") or ("error" if error else "unknown"))
    err = error or str(result.get("error") or "")
    kind = classify_error(err, status)

    # Success path — no heal needed
    if status in {"success", "pending", "ok"} and not error:
        return {
            "status": "success",
            "healed": False,
            "tool": tool,
            "classification": "ok",
            "heal_steps": [],
            "result": result,
            "needs_review": bool(result.get("needs_review", False)),
        }

    steps.append({"action": "classify", "classification": kind, "error": err or None})

    if kind == "circuit_open" and reset_circuit:
        DEFAULT_BREAKER.reset()
        steps.append({"action": "reset_circuit", "ok": True})

    if kind in {"transient", "circuit_open", "error"} and retry_fn is not None:
        steps.append({"action": "retry", "attempt": 1})
        time.sleep(0.05)
        try:
            retried = retry_fn()
        except CircuitOpenError as exc:
            steps.append({"action": "retry_failed", "error": str(exc)})
            return {
                "status": "needs_review",
                "healed": False,
                "tool": tool,
                "classification": "circuit_open",
                "heal_steps": steps,
                "error": str(exc),
                "needs_review": True,
                "resume_hint": "Circuit still open after heal — pause and inspect circuit_status.",
            }
        except Exception as exc:  # noqa: BLE001
            steps.append({"action": "retry_failed", "error": str(exc)})
            return {
                "status": "needs_review",
                "healed": False,
                "tool": tool,
                "classification": kind,
                "heal_steps": steps,
                "error": str(exc),
                "needs_review": True,
                "resume_hint": "Retry failed — escalate to human or shadow trajectory.",
            }

        retried_status = str(retried.get("status") or "")
        steps.append({"action": "retry_result", "status": retried_status})
        if retried_status in {"success", "pending", "ok"}:
            return {
                "status": "success",
                "healed": True,
                "tool": tool,
                "classification": kind,
                "heal_steps": steps,
                "result": retried,
                "needs_review": bool(retried.get("needs_review", False)),
            }
        result = retried
        err = str(retried.get("error") or err)
        kind = classify_error(err, retried_status)

    if kind == "not_found":
        hint = "Entity missing — verify id or load Spike A / warehouse."
    elif kind == "denied":
        hint = "Policy denied — do not retry with the same payload."
    else:
        hint = "Stop inventing data; use shadow_cash_app_trajectory or flag_for_human_review."

    steps.append({"action": "escalate", "needs_review": True})
    return {
        "status": "needs_review",
        "healed": False,
        "tool": tool,
        "classification": kind,
        "heal_steps": steps,
        "error": err or None,
        "result": result,
        "needs_review": True,
        "resume_hint": hint,
    }


def run_with_heal(tool: str, fn: HealFn, *, reset_circuit: bool = True) -> dict[str, Any]:
    """Execute ``fn``; on failure/exception apply ``heal_result`` with one retry."""
    try:
        result = fn()
    except CircuitOpenError as exc:
        return heal_result(
            tool=tool,
            error=str(exc),
            result={"status": "circuit_open", "error": str(exc)},
            retry_fn=fn,
            reset_circuit=reset_circuit,
        )
    except Exception as exc:  # noqa: BLE001
        return heal_result(
            tool=tool,
            error=str(exc),
            result={"status": "error", "error": str(exc)},
            retry_fn=fn,
            reset_circuit=reset_circuit,
        )

    status = str(result.get("status") or "")
    if status in {"success", "pending", "ok"}:
        return heal_result(tool=tool, result=result, retry_fn=None)

    return heal_result(tool=tool, result=result, retry_fn=fn, reset_circuit=reset_circuit)
