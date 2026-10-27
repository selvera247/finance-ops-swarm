"""Side effects after HITL decisions (e.g. apply cash-app match on approve)."""

from __future__ import annotations

from typing import Any

from finance_ops.runtime.hitl import PendingApproval


def after_decision(item: PendingApproval) -> dict[str, Any]:
    """Run post-decision effects. Safe to call from tools and HITL server."""
    effects: dict[str, Any] = {"applied": False, "hubspot_task": None}

    if item.status == "approved":
        kind = (item.kind or "").strip().lower()
        if kind in {"cash_app_match", "payment_match", "cash_app"}:
            payment_id = str(item.payload.get("payment_id") or "")
            invoice_id = str(
                item.payload.get("invoice_id")
                or item.payload.get("recommended_invoice_id")
                or ""
            )
            if not payment_id or not invoice_id:
                effects.update(
                    {
                        "applied": False,
                        "reason": "missing_payment_or_invoice",
                        "payload": item.payload,
                    }
                )
            else:
                from data_plane import repository as repo

                result = repo.apply_payment_match(payment_id, invoice_id)
                effects.update(
                    {
                        "applied": bool(result.get("ok")),
                        "kind": kind,
                        "payment_id": payment_id,
                        "invoice_id": invoice_id,
                        "result": result,
                    }
                )
        else:
            effects["reason"] = "no_effect_for_kind"
            effects["kind"] = kind

    # D6 — HubSpot task handoff (policy + audit; soft-fail). Runs on approve or reject.
    effects["hubspot_task"] = _hubspot_task_handoff(item)
    return effects


def _hubspot_task_handoff(item: PendingApproval) -> dict[str, Any]:
    """Create a HubSpot follow-up task after HITL. Soft-fail: never raises."""
    from finance_ops.governance.audit import append_audit
    from finance_ops.governance.policy import requires_approval
    from finance_ops.runtime.sanitize import sanitize_hubspot_text

    try:
        decision = requires_approval(
            "hubspot_task_handoff",
            float(item.amount or 0),
            vendor_risk=str(item.payload.get("vendor_risk") or "unknown"),
            agent="hitl_runtime",
        )
        append_audit(
            event="hubspot_task_handoff_policy",
            agent="hitl_runtime",
            decision=decision.outcome,
            tool="create_task",
            args={
                "approval_id": item.approval_id,
                "kind": item.kind,
                "status": item.status,
            },
            reason=decision.reason,
        )
        if decision.denied:
            return {
                "status": "denied",
                "reason": decision.reason,
                "soft_fail": False,
            }

        subject = sanitize_hubspot_text(
            f"HITL {item.status}: {item.kind} {item.approval_id}",
            max_len=256,
        )
        body = sanitize_hubspot_text(
            f"Approval {item.approval_id} decided={item.status}. "
            f"Summary: {item.summary}. Amount: {item.amount}. "
            f"Payload keys: {sorted((item.payload or {}).keys())}",
            max_len=4000,
        )
        company_id = str(item.payload.get("company_id") or item.payload.get("hubspot_company_id") or "")
        deal_id = str(item.payload.get("deal_id") or item.payload.get("hubspot_deal_id") or "")

        from finance_ops.tools.hubspot_tools import create_task

        out = create_task(
            subject,
            body=body,
            company_id=company_id,
            deal_id=deal_id,
        )
        append_audit(
            event="hubspot_task_handoff",
            agent="hitl_runtime",
            decision="allow" if out.get("status") == "success" else "error",
            tool="create_task",
            args={"approval_id": item.approval_id},
            reason=out.get("error") or out.get("status"),
            extra={
                "task_id": out.get("task_id"),
                "hubspot_status": out.get("status"),
            },
        )
        # Soft-fail: CRM/token errors do not undo HITL decision
        if out.get("status") != "success":
            return {
                "status": "soft_fail",
                "hubspot": out,
                "soft_fail": True,
            }
        return {"status": "success", "hubspot": out, "soft_fail": False}
    except Exception as exc:  # noqa: BLE001
        append_audit(
            event="hubspot_task_handoff",
            agent="hitl_runtime",
            decision="error",
            tool="create_task",
            args={"approval_id": item.approval_id},
            reason=str(exc),
            extra={"soft_fail": True},
        )
        return {"status": "soft_fail", "error": str(exc), "soft_fail": True}
