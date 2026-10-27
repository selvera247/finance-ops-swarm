"""ADK callbacks for governance (RBAC + agent lifecycle)."""

from __future__ import annotations

from typing import Any, Optional

from finance_ops.governance.audit import append_audit
from finance_ops.governance.rbac import is_tool_allowed
from finance_ops.governance.registry import is_invocation_allowed, touch_last_run


def _tool_name(tool: Any) -> str:
    name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
    return str(name or "").strip()


def before_tool_rbac(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
) -> Optional[dict[str, Any]]:
    """Deny tools not on the agent allowlist. Non-None return skips the tool call."""
    agent = str(getattr(tool_context, "agent_name", "") or "").strip()
    tool_name = _tool_name(tool)
    try:
        allowed, reason = is_tool_allowed(agent, tool_name)
    except Exception as exc:  # noqa: BLE001 — fail closed
        allowed, reason = False, f"rbac_error:{exc}"

    if allowed:
        append_audit(
            event="tool_rbac",
            agent=agent or "unknown",
            tool=tool_name or "unknown",
            args=args if isinstance(args, dict) else {},
            decision="allow",
            reason=reason,
        )
        return None

    append_audit(
        event="tool_rbac",
        agent=agent or "unknown",
        tool=tool_name or "unknown",
        args=args if isinstance(args, dict) else {},
        decision="deny",
        reason=reason,
    )
    return {
        "status": "denied",
        "error": "rbac_denied",
        "agent": agent,
        "tool": tool_name,
        "reason": reason,
        "needs_review": True,
    }


def before_agent_registry(callback_context: Any) -> Optional[Any]:
    """Refuse retired / unknown agents before the LLM run (fail closed)."""
    agent = str(getattr(callback_context, "agent_name", "") or "").strip()
    try:
        ok, reason = is_invocation_allowed(agent)
    except Exception as exc:  # noqa: BLE001
        ok, reason = False, f"registry_error:{exc}"
    if ok:
        return None
    append_audit(
        event="agent_invoke",
        agent=agent or "unknown",
        decision="deny",
        reason=reason,
    )
    try:
        from google.genai import types

        return types.Content(
            role="model",
            parts=[
                types.Part(
                    text=(
                        f"Agent invocation refused by governance registry "
                        f"(agent={agent}, reason={reason})."
                    )
                )
            ],
        )
    except Exception:  # noqa: BLE001
        # If genai types unavailable, still block by returning a minimal truthy payload
        return {"status": "denied", "error": "agent_retired", "reason": reason}


def after_agent_registry(callback_context: Any) -> Optional[Any]:
    """Record last_run_at after each agent invocation."""
    agent = str(getattr(callback_context, "agent_name", "") or "").strip()
    if agent:
        touch_last_run(agent)
    return None
