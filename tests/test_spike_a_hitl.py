"""Spike A: cash-app approval applies match on HITL approve."""

from __future__ import annotations

from data_plane import repository as repo
from finance_ops.tools.payment_tools import request_cash_app_approval, suggest_payment_match
from finance_ops.tools.runtime_tools import decide_approval
from scripts.load_spike_a import load


def setup_function() -> None:
    load(replace_customers=True)


def test_request_and_approve_applies_match():
    pending = request_cash_app_approval("PAY-1001", notify_slack=False)
    assert pending["status"] == "pending"
    assert pending["invoice_id"] == "INV-84219"
    approval = pending["approval"]
    decided = decide_approval(
        approval["approval_id"],
        "approved",
        resume_token=approval["resume_token"],
        actor="test",
    )
    assert decided["status"] == "approved"
    assert decided["effect"]["applied"] is True
    payment = repo.get_payment("PAY-1001")
    assert payment is not None
    assert payment["status"] == "matched"
    assert payment["matched_invoice_id"] == "INV-84219"


def test_orphan_cash_opens_escalate_without_apply():
    pending = request_cash_app_approval("PAY-3001", notify_slack=False)
    assert pending["status"] == "pending"
    assert pending["invoice_id"] is None
    assert pending["approval"]["kind"] == "cash_app_escalate"
    approval = pending["approval"]
    decided = decide_approval(
        approval["approval_id"],
        "rejected",
        resume_token=approval["resume_token"],
        actor="test",
    )
    assert decided["status"] == "rejected"
    assert decided["effect"]["applied"] is False
    payment = repo.get_payment("PAY-3001")
    assert payment is not None
    assert payment["status"] == "unmatched"


def test_suggest_still_needs_review():
    out = suggest_payment_match("PAY-2001")
    assert out["needs_review"] is True
    assert len(out["candidates"]) >= 2
