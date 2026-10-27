"""Slack HITL notify + durable signal."""

from __future__ import annotations

from pathlib import Path

from finance_ops.runtime.durable import DurableWorkflow
from finance_ops.runtime.hitl import ApprovalStore
from finance_ops.runtime.slack_hitl import (
    approval_links,
    notify_slack,
    parse_slack_interaction_payload,
    slack_message_blocks,
)
from finance_ops.tools.runtime_tools import get_approval, request_approval


def test_slack_blocks_and_links(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HITL_PUBLIC_BASE_URL", "http://example.test:8787")
    store = ApprovalStore(root=tmp_path / "hitl")
    appr = store.create(kind="write_off", amount=125.0, summary="test")
    links = approval_links(appr)
    assert appr.approval_id in links["approve"]
    assert "token=" in links["approve"]
    blocks = slack_message_blocks(appr)
    assert blocks[0]["type"] == "header"
    assert any(b.get("type") == "actions" for b in blocks)


def test_notify_slack_without_webhook(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    store = ApprovalStore(root=tmp_path / "hitl")
    appr = store.create(kind="write_off", amount=10.0, summary="x")
    result = notify_slack(appr)
    assert result["sent"] is False
    assert result["channel"] == "none"
    assert "approve" in result["links"]


def test_notify_slack_loads_dotenv(monkeypatch, tmp_path: Path) -> None:
    """CLI one-liners should pick SLACK_WEBHOOK_URL from finance_ops/.env."""
    import finance_ops.runtime.slack_hitl as slack_mod

    runtime = tmp_path / "finance_ops" / "runtime"
    runtime.mkdir(parents=True)
    (tmp_path / "finance_ops" / ".env").write_text(
        "SLACK_WEBHOOK_URL=https://hooks.example.test/from-dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(slack_mod, "__file__", str(runtime / "slack_hitl.py"))
    monkeypatch.setattr(slack_mod, "_DOTENV_LOADED", False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

    calls: list[str] = []

    def fake_post(url, payload, headers=None):
        calls.append(url)
        return {"ok": True}

    monkeypatch.setattr(slack_mod, "_post_json", fake_post)
    store = ApprovalStore(root=tmp_path / "hitl")
    appr = store.create(kind="write_off", amount=10.0, summary="x")
    result = notify_slack(appr)
    assert result["sent"] is True
    assert calls == ["https://hooks.example.test/from-dotenv"]


def test_notify_slack_webhook_mock(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.test/T")
    calls: list[dict] = []

    def fake_post(url, payload, headers=None):
        calls.append({"url": url, "payload": payload})
        return {"ok": True}

    monkeypatch.setattr("finance_ops.runtime.slack_hitl._post_json", fake_post)
    store = ApprovalStore(root=tmp_path / "hitl")
    appr = store.create(kind="write_off", amount=10.0, summary="x")
    result = notify_slack(appr)
    assert result["sent"] is True
    assert calls and "blocks" in calls[0]["payload"]


def test_request_approval_tool_includes_slack(monkeypatch) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    out = request_approval(
        kind="write_off",
        amount=125.0,
        summary="INV-1001 small",
        related_ids="INV-1001",
    )
    assert out["status"] == "pending"
    assert "links" in out
    assert out["slack"]["sent"] is False
    got = get_approval(out["approval"]["approval_id"])
    assert got["approval"]["status"] == "pending"


def test_parse_slack_interaction() -> None:
    import json

    payload = json.dumps(
        {
            "user": {"username": "cj"},
            "actions": [{"action_id": "hitl_approve", "value": "APPR-1:tok:approved"}],
            "message": {"ts": "1.2"},
        }
    )
    parsed = parse_slack_interaction_payload(payload)
    assert parsed["decision"] == "approved"
    assert parsed["user"] == "cj"


def test_durable_signal(tmp_path: Path) -> None:
    wf = DurableWorkflow(root=tmp_path / "wf")
    state = wf.create(["a"])
    signaled = wf.signal(state.run_id, "hitl_approved", {"approval_id": "APPR-1"})
    assert signaled.meta["signal_hitl_approved"]["approval_id"] == "APPR-1"
    assert len(signaled.meta["signals"]) == 1
