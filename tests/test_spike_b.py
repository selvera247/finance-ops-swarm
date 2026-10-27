from __future__ import annotations

from scripts.load_spike_b import load
from finance_ops.tools.portal_spike_tools import (
    classify_portal_exception,
    request_portal_extract_review,
    spike_b_walkthrough,
)
from finance_ops.tools.shadow_tools import shadow_spike_b_walkthrough


def test_load_and_classify_walkthrough() -> None:
    loaded = load()
    assert loaded["status"] == "success"
    assert loaded["counts"]["spike_b_rows"] >= 8

    clean = classify_portal_exception("CLM-B1001")
    assert clean["status"] == "success"
    assert clean["disposition"] == "accept_remittance"
    assert "INV-84219" in clean["suggested_invoice_ids"]

    denied = classify_portal_exception("CLM-B2001")
    assert denied["disposition"] == "escalate_appeal"
    assert denied["needs_review"] is True

    orphan = classify_portal_exception("CLM-B3001")
    assert orphan["disposition"] == "escalate_orphan"


def test_hitl_and_shadow(monkeypatch) -> None:
    load()
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    pending = request_portal_extract_review("CLM-B2001", notify_slack=False)
    assert pending["status"] == "pending"
    assert pending["approval"]["kind"] == "portal_claim_denied"

    walk = spike_b_walkthrough()
    assert walk["status"] == "success"
    assert len(walk["walkthrough"]) == 3

    shadow = shadow_spike_b_walkthrough()
    assert shadow["mutated"] is False
    assert len(shadow["bundle"]["trajectories"]) == 3
