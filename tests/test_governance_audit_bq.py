"""Governance audit BigQuery shipper — opt-in, best-effort, row shape."""

from __future__ import annotations

from typing import Any

import pytest

from finance_ops.governance import audit as audit_mod
from finance_ops.governance.audit_bq import (
    audit_bq_enabled,
    record_to_bq_row,
    ship_audit_jsonl,
    ship_audit_record,
)


def test_audit_bq_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINANCE_OPS_AUDIT_BQ", raising=False)
    assert audit_bq_enabled() is False
    out = ship_audit_record({"event": "tool_rbac", "agent": "x", "decision": "deny"})
    assert out["skipped"] is True


def test_record_to_bq_row_shape() -> None:
    row = record_to_bq_row(
        {
            "event_id": "AUD-abc",
            "ts": "2026-10-26T00:00:00+00:00",
            "event": "tool_rbac",
            "agent": "invoice_agent",
            "tool": "aging_summary",
            "args_hash": "deadbeef",
            "decision": "allow",
            "reason": "allow",
            "extra": {"k": 1},
        }
    )
    assert row["event_id"] == "AUD-abc"
    assert row["extra_json"] == '{"k": 1}'
    assert row["ingested_at"]


def test_append_audit_ships_when_enabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit_mod, "WAREHOUSE_DIR", tmp_path / "wh")
    monkeypatch.setenv("FINANCE_OPS_AUDIT_BQ", "true")

    calls: list[dict[str, Any]] = []

    def fake_ship(record: dict[str, Any]) -> dict[str, Any]:
        calls.append(record)
        return {"shipped": True, "event_id": record.get("event_id")}

    monkeypatch.setattr(
        "finance_ops.governance.audit_bq.ship_audit_record",
        fake_ship,
    )
    # append_audit imports ship inside function — patch module used after import
    import finance_ops.governance.audit_bq as bq_mod

    monkeypatch.setattr(bq_mod, "ship_audit_record", fake_ship)

    rec = audit_mod.append_audit(
        event="tool_rbac",
        agent="invoice_agent",
        decision="allow",
        tool="aging_summary",
    )
    assert rec["event_id"].startswith("AUD-")
    assert calls and calls[0]["event"] == "tool_rbac"
    assert rec.get("bq", {}).get("shipped") is True
    assert audit_mod.audit_path().is_file()


def test_ship_jsonl_backfill(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_AUDIT_BQ", "true")
    path = tmp_path / "audit.jsonl"
    path.write_text(
        '{"event":"lifecycle","agent":"a","decision":"retired"}\n',
        encoding="utf-8",
    )
    shipped: list[Any] = []

    def fake_ship(record: dict[str, Any]) -> dict[str, Any]:
        shipped.append(record)
        return {"shipped": True, "event_id": "AUD-x"}

    monkeypatch.setattr(
        "finance_ops.governance.audit_bq.ship_audit_record",
        fake_ship,
    )
    out = ship_audit_jsonl(path)
    assert out["status"] == "success"
    assert out["shipped"] == 1
    assert shipped
