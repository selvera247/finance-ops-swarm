from __future__ import annotations

import json

from finance_ops.lib.evidence import record_evidence
from finance_ops.runtime.circuit_breaker import DEFAULT_BREAKER
from finance_ops.runtime.context_budget import pack_context
from finance_ops.runtime.sanitize import sanitize_for_export
from finance_ops.runtime.self_heal import heal_result, run_with_heal
from finance_ops.tools.craft_tools import budget_pack_context, heal_tool_result, sanitize_payload


def test_sanitize_redacts_secrets_keeps_ids() -> None:
    raw = {
        "payment_id": "PAY-1001",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/xxx",
        "note": "Bearer eyJhbGciOiJIUzI1NiJ9.aaaa.bbbb",
        "account": "1234567890123456",
        "nested": {"api_key": "sk-abcdefghijklmnopqrstuvwxyz"},
    }
    clean = sanitize_for_export(raw)
    assert clean["payment_id"] == "PAY-1001"
    assert clean["SLACK_WEBHOOK_URL"] == "[REDACTED]"
    assert "hooks.slack.com" not in clean["note"]
    assert clean["account"] == "[REDACTED]"
    assert clean["nested"]["api_key"] == "[REDACTED]"


def test_evidence_sanitizes_inputs() -> None:
    meta = record_evidence(
        agent="test",
        action="unit",
        inputs={"token": "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
        outputs={"ok": True, "needs_review": False},
        sources=["test"],
    )
    path = meta["path"]
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["inputs"]["token"] == "[REDACTED]"
    assert data["governance"]["sanitized"] is True


def test_pack_payments_budget() -> None:
    payload = {
        "status": "success",
        "payments": [
            {
                "payment_id": f"PAY-{i}",
                "customer_id": "C-1042",
                "amount": float(i),
                "status": "unmatched",
                "reference": "x" * 500,
                "extra_field": "drop-me",
            }
            for i in range(20)
        ],
    }
    out = pack_context(payload, kind="payments", max_items=5, max_chars=50_000)
    assert out["budget"]["omitted_items"] == 15
    assert len(out["packed"]["payments"]) == 5
    assert "extra_field" not in out["packed"]["payments"][0]
    assert len(out["packed"]["payments"][0]["reference"]) <= 240


def test_heal_retries_transient() -> None:
    DEFAULT_BREAKER.reset()
    calls = {"n": 0}

    def flaky() -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            return {"status": "error", "error": "connection timeout", "needs_review": True}
        return {"status": "success", "recommendation": "INV-1", "needs_review": True}

    out = run_with_heal("suggest_payment_match", flaky)
    assert out["healed"] is True
    assert out["status"] == "success"
    assert calls["n"] == 2
    assert out["result"]["recommendation"] == "INV-1"


def test_heal_circuit_open_resets_and_escalates() -> None:
    DEFAULT_BREAKER.reset()
    DEFAULT_BREAKER.max_tool_calls = 1
    DEFAULT_BREAKER.record_tool("a")
    try:
        DEFAULT_BREAKER.record_tool("b")
    except Exception:
        pass

    out = heal_result(
        tool="x",
        result={"status": "circuit_open", "error": "circuit open: tool_calls"},
        retry_fn=None,
    )
    assert out["needs_review"] is True
    assert out["classification"] == "circuit_open"
    assert any(s.get("action") == "reset_circuit" for s in out["heal_steps"])
    # breaker should be reset
    assert DEFAULT_BREAKER.snapshot()["open"] is False
    DEFAULT_BREAKER.max_tool_calls = 25


def test_craft_tools() -> None:
    packed = budget_pack_context(
        json.dumps({"payments": [{"payment_id": "PAY-1", "amount": 1, "status": "unmatched"}]}),
        "payments",
        8,
        4000,
    )
    assert packed["status"] == "success"
    assert "evidence_id" in packed["evidence"]

    san = sanitize_payload('{"api_key":"sk-abcdefghijklmnopqrstuvwxyz","id":"PAY-1"}')
    assert san["sanitized"]["api_key"] == "[REDACTED]"
    assert san["sanitized"]["id"] == "PAY-1"

    healed = heal_tool_result("demo", '{"status":"not_found","error":"missing"}', "")
    assert healed["needs_review"] is True
    assert healed["classification"] == "not_found"
