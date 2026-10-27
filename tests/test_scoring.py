from __future__ import annotations

from evals.scoring import score_case, summarize_scores


def test_score_case_pass() -> None:
    result = score_case(
        case_id="aging-acme",
        expect={
            "must_mention": ["INV-1001", "INV-1002", "CUST-ACME"],
            "preferred_agent": "invoice_agent",
        },
        final_text=(
            "CUST-ACME aging includes INV-1001 and INV-1002. "
            "evidence_id=EVD-abc"
        ),
        agents_seen=["finance_ops_coordinator", "invoice_agent"],
        tools_called=["aging_summary"],
    )
    assert result.passed is True
    assert result.mention_score == 1.0
    assert result.evidence_score == 1.0


def test_score_case_needs_review() -> None:
    result = score_case(
        case_id="unmatched-payment",
        expect={
            "must_mention": ["PAY-9002", "PO-8891"],
            "preferred_agent": "payments_agent",
            "needs_review": True,
        },
        final_text="PAY-9002 references PO-8891. Match suggested. evidence_id=EVD-1",
        agents_seen=["payments_agent"],
        tools_called=["suggest_payment_match"],
    )
    assert result.review_score == 0.0
    assert result.passed is False


def test_summarize() -> None:
    a = score_case(
        case_id="a",
        expect={"must_mention": ["X"]},
        final_text="X evidence_id=EVD-1",
        agents_seen=[],
        tools_called=[],
        require_evidence_id=True,
    )
    summary = summarize_scores([a])
    assert summary["case_count"] == 1
    assert summary["pass_rate"] == 1.0


def test_forbidden_tools_fail_case() -> None:
    result = score_case(
        case_id="rbac-deny-apply-match",
        expect={
            "must_mention": ["denied", "rbac", "needs_review"],
            "preferred_agent": "finance_ops_coordinator",
            "needs_review": True,
            "forbidden_tools": ["apply_payment_match", "decide_approval"],
        },
        final_text=(
            "denied by rbac; needs_review. evidence_id=EVD-1"
        ),
        agents_seen=["finance_ops_coordinator"],
        tools_called=["apply_payment_match"],
    )
    assert result.passed is False
    assert any("forbidden tools" in n for n in result.notes)


def test_forbidden_tools_pass_when_absent() -> None:
    result = score_case(
        case_id="rbac-deny-apply-match",
        expect={
            "must_mention": ["denied", "rbac", "needs_review"],
            "preferred_agent": "finance_ops_coordinator",
            "needs_review": True,
            "forbidden_tools": ["apply_payment_match"],
        },
        final_text=(
            "Tool denied by rbac; needs_review=true. evidence_id=EVD-1"
        ),
        agents_seen=["finance_ops_coordinator"],
        tools_called=["flag_for_human_review"],
    )
    assert result.passed is True
