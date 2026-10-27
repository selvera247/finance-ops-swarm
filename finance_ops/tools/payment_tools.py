from __future__ import annotations

from typing import Any

from data_plane import repository as repo
from finance_ops.lib.evidence import record_evidence
from finance_ops.runtime.circuit_breaker import DEFAULT_BREAKER, CircuitOpenError


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in row.items()}


def _guard(tool_name: str) -> None:
    DEFAULT_BREAKER.record_tool(tool_name)


def lookup_payment(payment_id: str) -> dict[str, Any]:
    payment_id = payment_id.strip().upper()
    match = repo.get_payment(payment_id)
    result = (
        {"status": "not_found", "payment_id": payment_id, "needs_review": True}
        if not match
        else {"status": "success", "payment": _clean(match), "needs_review": False}
    )
    result["evidence"] = record_evidence(
        agent="payments_agent", action="lookup_payment",
        inputs={"payment_id": payment_id}, outputs=result,
        sources=[repo.source_label()] if match else [],
    )
    return result


def list_unmatched_payments(customer_id: str | None = None) -> dict[str, Any]:
    rows = [_clean(r) for r in repo.list_payments(customer_id=customer_id, unmatched_only=True)]
    result = {"status": "success", "count": len(rows), "payments": rows, "needs_review": len(rows) > 0}
    result["evidence"] = record_evidence(
        agent="payments_agent", action="list_unmatched_payments",
        inputs={"customer_id": customer_id}, outputs={"count": len(rows)},
        sources=[repo.source_label()],
    )
    return result


def suggest_payment_match(payment_id: str) -> dict[str, Any]:
    payment_id = payment_id.strip().upper()
    payment = repo.get_payment(payment_id)
    if not payment:
        result = {"status": "not_found", "payment_id": payment_id, "needs_review": True}
        result["evidence"] = record_evidence(
            agent="payments_agent", action="suggest_payment_match",
            inputs={"payment_id": payment_id}, outputs=result, sources=[],
        )
        return result
    candidates = []
    for inv in repo.list_invoices(customer_id=payment["customer_id"], open_only=True):
        score, reasons = 0.0, []
        ref = (payment.get("reference") or "").upper()
        if inv["invoice_id"] in ref:
            score += 0.7
            reasons.append("invoice_id_in_reference")
        if inv.get("po_number") and str(inv["po_number"]) in ref:
            score += 0.4
            reasons.append("po_in_reference")
        amount_delta = abs(float(inv["amount"]) - float(payment["amount"]))
        if amount_delta <= max(1.0, float(inv["amount"]) * 0.005):
            score += 0.5
            reasons.append("amount_within_tolerance")
        elif float(payment["amount"]) < float(inv["amount"]):
            score += 0.2
            reasons.append("possible_partial")
        if score > 0:
            candidates.append({
                "invoice_id": inv["invoice_id"], "score": round(score, 2), "reasons": reasons,
                "invoice_amount": inv["amount"], "invoice_status": inv["status"],
            })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    result = {
        "status": "success", "payment": _clean(payment), "candidates": candidates[:5],
        "needs_review": True, "recommendation": candidates[0]["invoice_id"] if candidates else None,
    }
    result["evidence"] = record_evidence(
        agent="payments_agent", action="suggest_payment_match",
        inputs={"payment_id": payment_id},
        outputs={"recommendation": result["recommendation"], "candidate_count": len(candidates)},
        sources=[repo.source_label(), "policy:POL-RECON-01"],
    )
    return result


def apply_payment_match(payment_id: str, invoice_id: str) -> dict[str, Any]:
    """Apply a match immediately (prefer request_cash_app_approval + HITL in demos)."""
    try:
        _guard("apply_payment_match")
    except CircuitOpenError as exc:
        return {"status": "circuit_open", "error": str(exc), "needs_review": True}
    from finance_ops.governance.policy import requires_approval

    payment_id = payment_id.strip().upper()
    invoice_id = invoice_id.strip().upper()
    payment = repo.get_payment(payment_id)
    amount = float((payment or {}).get("amount") or 0)
    decision = requires_approval(
        "apply_payment_match",
        amount,
        vendor_risk="unknown",
        agent="payments_agent",
    )
    if decision.denied:
        return {
            "status": "denied",
            "error": "policy_denied",
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "policy": {"outcome": decision.outcome, "reason": decision.reason},
            "needs_review": True,
        }
    if decision.needs_human:
        return {
            "status": "needs_approval",
            "error": "policy_requires_human",
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "policy": {"outcome": decision.outcome, "reason": decision.reason},
            "hint": "Call request_cash_app_approval — direct apply is blocked by policy",
            "needs_review": True,
        }

    applied = repo.apply_payment_match(payment_id, invoice_id)
    result = {
        "status": "success" if applied.get("ok") else "error",
        "applied": applied,
        "policy": {"outcome": decision.outcome, "reason": decision.reason},
        "needs_review": not applied.get("ok"),
    }
    result["evidence"] = record_evidence(
        agent="payments_agent",
        action="apply_payment_match",
        inputs={"payment_id": payment_id, "invoice_id": invoice_id},
        outputs={**applied, "policy": decision.outcome},
        sources=[repo.source_label(), "governance:policy"],
    )
    return result


def request_cash_app_approval(
    payment_id: str,
    invoice_id: str = "",
    notify_slack: bool = True,
) -> dict[str, Any]:
    """Suggest (if needed) then open Slack/HITL gate; approve applies the match."""
    try:
        _guard("request_cash_app_approval")
    except CircuitOpenError as exc:
        return {"status": "circuit_open", "error": str(exc), "needs_review": True}

    from finance_ops.runtime.hitl import DEFAULT_STORE
    from finance_ops.runtime.slack_hitl import approval_links, notify_slack as slack_notify

    from finance_ops.governance.policy import requires_approval

    payment_id = payment_id.strip().upper()
    suggestion = suggest_payment_match(payment_id)
    if suggestion.get("status") != "success":
        return {**suggestion, "needs_review": True}

    invoice_id = (invoice_id or suggestion.get("recommendation") or "").strip().upper()
    payment = suggestion.get("payment") or {}
    amount = float(payment.get("amount") or 0)

    if not invoice_id:
        # Orphan cash — still open HITL for escalate/reject narrative
        summary = f"Cash app escalate: {payment_id} — no invoice candidates"
        kind = "cash_app_escalate"
        payload = {
            "payment_id": payment_id,
            "invoice_id": None,
            "candidates": suggestion.get("candidates") or [],
            "related_ids": [payment_id],
        }
    else:
        summary = f"Cash app match: {payment_id} → {invoice_id}"
        kind = "cash_app_match"
        payload = {
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "recommended_invoice_id": suggestion.get("recommendation"),
            "candidates": suggestion.get("candidates") or [],
            "related_ids": [payment_id, invoice_id],
        }

    decision = requires_approval(
        kind,
        amount,
        vendor_risk="unknown",
        agent="payments_agent",
    )
    if decision.denied:
        return {
            "status": "denied",
            "error": "policy_denied",
            "payment_id": payment_id,
            "invoice_id": invoice_id or None,
            "suggestion": {
                "recommendation": suggestion.get("recommendation"),
                "candidates": suggestion.get("candidates"),
            },
            "policy": {"outcome": decision.outcome, "reason": decision.reason},
            "needs_review": True,
        }

    # Policy allow → auto-apply when an invoice is recommended (no HITL bypass of deny).
    if decision.allowed and invoice_id:
        applied = repo.apply_payment_match(payment_id, invoice_id)
        result = {
            "status": "auto_applied" if applied.get("ok") else "error",
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "applied": applied,
            "policy": {"outcome": decision.outcome, "reason": decision.reason},
            "needs_review": not applied.get("ok"),
        }
        result["evidence"] = record_evidence(
            agent="payments_agent",
            action="request_cash_app_approval",
            inputs={"payment_id": payment_id, "invoice_id": invoice_id},
            outputs={"auto_applied": True, "policy": decision.outcome, **applied},
            sources=[repo.source_label(), "governance:policy"],
        )
        return result

    payload["policy_reason"] = decision.reason
    approval = DEFAULT_STORE.create(
        kind=kind,
        amount=amount,
        summary=summary,
        payload=payload,
        currency=str(payment.get("currency") or "USD"),
    )
    links = approval_links(approval)
    slack = slack_notify(approval) if notify_slack else {"sent": False, "skipped": True}
    result = {
        "status": "pending",
        "payment_id": payment_id,
        "invoice_id": invoice_id or None,
        "suggestion": {
            "recommendation": suggestion.get("recommendation"),
            "candidates": suggestion.get("candidates"),
        },
        "approval": approval.model_dump(),
        "links": links,
        "slack": slack,
        "policy": {"outcome": decision.outcome, "reason": decision.reason},
        "needs_review": True,
        "resume_hint": (
            f"Approve to apply match, or reject to leave unmatched. "
            f"Slack button or {links.get('approve')}"
        ),
    }
    result["evidence"] = record_evidence(
        agent="payments_agent",
        action="request_cash_app_approval",
        inputs={"payment_id": payment_id, "invoice_id": invoice_id},
        outputs={
            "approval_id": approval.approval_id,
            "kind": kind,
            "slack_sent": slack.get("sent"),
            "policy": decision.outcome,
        },
        sources=[repo.source_label(), "hitl:approval_store", "slack:hitl", "governance:policy"],
    )
    return result
