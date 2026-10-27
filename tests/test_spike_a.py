"""Spike A cash-app sample loads and match suggestions."""

from __future__ import annotations

from scripts.load_spike_a import load
from finance_ops.tools.payment_tools import list_unmatched_payments, suggest_payment_match


def test_spike_a_load_and_walkthrough():
    result = load(replace_customers=True)
    assert result["status"] == "success"
    assert result["counts"]["payments"] == 13
    assert result["counts"]["invoices"] == 9

    unmatched = list_unmatched_payments()
    ids = {p["payment_id"] for p in unmatched["payments"]}
    assert "PAY-1001" in ids
    assert "PAY-2001" in ids
    assert "PAY-3001" in ids

    clean = suggest_payment_match("PAY-1001")
    assert clean["recommendation"] == "INV-84219"
    assert clean["needs_review"] is True

    ambiguous = suggest_payment_match("PAY-2001")
    cand_ids = {c["invoice_id"] for c in ambiguous["candidates"]}
    assert "INV-92001" in cand_ids
    assert "INV-92004" in cand_ids
    assert ambiguous["needs_review"] is True

    orphan = suggest_payment_match("PAY-3001")
    assert orphan["candidates"] == []
    assert orphan["recommendation"] is None
    assert orphan["needs_review"] is True
