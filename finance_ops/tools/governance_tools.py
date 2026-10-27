from __future__ import annotations

from typing import Any

from finance_ops.lib.evidence import list_evidence, load_evidence, record_evidence


def get_evidence(evidence_id: str) -> dict[str, Any]:
    record = load_evidence(evidence_id.strip())
    if not record:
        return {"status": "not_found", "evidence_id": evidence_id, "needs_review": True}
    return {"status": "success", "evidence": record, "needs_review": False}


def recent_evidence(limit: int = 10) -> dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    records = list_evidence(limit=limit)
    return {"status": "success", "count": len(records), "evidence": records, "needs_review": False}


def flag_for_human_review(
    reason: str,
    related_ids: str = "",
    severity: str = "medium",
    amount: float = 0.0,
    create_approval: bool = False,
) -> dict[str, Any]:
    """Flag for review; optionally serialize a HITL PendingApproval (#8)."""
    severity = severity.lower().strip()
    if severity not in {"low", "medium", "high"}:
        severity = "medium"
    related = [x.strip() for x in related_ids.split(",") if x.strip()]
    result: dict[str, Any] = {
        "status": "flagged",
        "reason": reason,
        "related_ids": related,
        "severity": severity,
        "needs_review": True,
    }
    if create_approval or amount > 0:
        from finance_ops.runtime.hitl import DEFAULT_STORE

        approval = DEFAULT_STORE.create(
            kind="human_review",
            amount=float(amount),
            summary=reason,
            payload={"related_ids": related, "severity": severity},
        )
        result["approval"] = approval.model_dump()
        result["resume_hint"] = (
            f"python -m finance_ops.runtime.hitl_server → "
            f"/approve?id={approval.approval_id}&token={approval.resume_token}"
        )
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="flag_for_human_review",
        inputs={
            "reason": reason,
            "related_ids": related_ids,
            "severity": severity,
            "amount": amount,
            "create_approval": create_approval,
        },
        outputs={
            "status": "flagged",
            "approval_id": (result.get("approval") or {}).get("approval_id"),
        },
        sources=["governance:manual_flag", "hitl:approval_store"],
    )
    return result
