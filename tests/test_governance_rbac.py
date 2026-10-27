"""D1 governance RBAC — deny-by-default, coordinator cannot mutate approvals/payments."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from finance_ops.governance.audit import append_audit, args_hash, audit_path
from finance_ops.governance.callbacks import before_tool_rbac
from finance_ops.governance import rbac
from finance_ops.governance.rbac import (
    APPROVAL_MUTATING_TOOLS,
    HUBSPOT_READ_TOOLS,
    HUBSPOT_WRITE_TOOLS,
    PAYMENT_TOOLS,
    is_tool_allowed,
)


def test_deny_by_default_unknown_agent() -> None:
    ok, reason = is_tool_allowed("no_such_agent", "aging_summary")
    assert ok is False
    assert reason == "unknown_agent"


def test_deny_by_default_unknown_tool_on_known_agent() -> None:
    ok, reason = is_tool_allowed("invoice_agent", "apply_payment_match")
    assert ok is False
    assert reason == "tool_not_in_allowlist"


def test_invoice_agent_allows_aging() -> None:
    ok, reason = is_tool_allowed("invoice_agent", "aging_summary")
    assert ok is True
    assert reason == "allow"


def test_root_cannot_call_payment_tools() -> None:
    for tool in sorted(PAYMENT_TOOLS):
        ok, reason = is_tool_allowed("finance_ops_coordinator", tool)
        assert ok is False, tool
        assert "denied" in reason or reason == "tool_not_in_allowlist"


def test_root_cannot_call_approval_mutating_tools() -> None:
    for tool in sorted(APPROVAL_MUTATING_TOOLS):
        ok, reason = is_tool_allowed("finance_ops_coordinator", tool)
        assert ok is False, tool


def test_payments_agent_can_request_and_decide_approval() -> None:
    assert is_tool_allowed("payments_agent", "request_approval")[0] is True
    assert is_tool_allowed("payments_agent", "decide_approval")[0] is True
    assert is_tool_allowed("payments_agent", "apply_payment_match")[0] is True


def test_before_tool_callback_denies_and_audits(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "finance_ops.governance.audit.WAREHOUSE_DIR",
        tmp_path / "wh",
    )
    # re-import path helper uses patched WAREHOUSE_DIR via audit module
    from finance_ops.governance import audit as audit_mod

    monkeypatch.setattr(audit_mod, "WAREHOUSE_DIR", tmp_path / "wh")

    tool = SimpleNamespace(name="decide_approval")
    ctx = SimpleNamespace(agent_name="finance_ops_coordinator")
    out = before_tool_rbac(tool, {"approval_id": "APPR-x"}, ctx)
    assert out is not None
    assert out["status"] == "denied"
    assert out["tool"] == "decide_approval"
    path = audit_mod.audit_path()
    assert path.is_file()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    assert '"decision": "deny"' in lines[-1]


def test_before_tool_callback_allows_passthrough(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from finance_ops.governance import audit as audit_mod

    monkeypatch.setattr(audit_mod, "WAREHOUSE_DIR", tmp_path / "wh")
    tool = SimpleNamespace(name="aging_summary")
    ctx = SimpleNamespace(agent_name="invoice_agent")
    assert before_tool_rbac(tool, {"customer_id": "CUST-ACME"}, ctx) is None


def test_fail_closed_when_policy_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rbac, "AGENT_TOOL_POLICY", {})
    ok, reason = is_tool_allowed("invoice_agent", "aging_summary")
    assert ok is False
    assert "policy_unavailable" in reason


def test_registered_tools_match_allowlist() -> None:
    """Every tool attached to an Agent must be on that agent's RBAC allowlist."""
    from finance_ops.agent import root_agent
    from finance_ops.specialists.contracts_agent import contracts_agent
    from finance_ops.specialists.invoice_agent import invoice_agent
    from finance_ops.specialists.payments_agent import payments_agent
    from finance_ops.specialists.reconciliation_agent import reconciliation_agent

    agents = [
        root_agent,
        invoice_agent,
        payments_agent,
        contracts_agent,
        reconciliation_agent,
    ]
    for agent in agents:
        assert agent.before_tool_callback is before_tool_rbac
        for tool in agent.tools or []:
            name = getattr(tool, "__name__", None) or getattr(tool, "name", None)
            assert name, tool
            ok, reason = is_tool_allowed(agent.name, str(name))
            assert ok, f"{agent.name}.{name} not allowlisted: {reason}"


def test_args_hash_stable() -> None:
    assert args_hash({"a": 1, "b": 2}) == args_hash({"b": 2, "a": 1})


def test_hubspot_read_allowed_on_invoice_contracts_reconciliation() -> None:
    from finance_ops.governance.rbac import AGENT_TOOL_POLICY

    for agent in ("invoice_agent", "contracts_agent", "reconciliation_agent"):
        allowed = AGENT_TOOL_POLICY[agent] & HUBSPOT_READ_TOOLS
        assert allowed, agent
        for tool in sorted(allowed):
            ok, reason = is_tool_allowed(agent, tool)
            assert ok is True, f"{agent}.{tool}: {reason}"
        # Specialist-specific composites stay scoped
        if agent == "invoice_agent":
            assert is_tool_allowed(agent, "enrich_aging_hubspot")[0] is True
            assert is_tool_allowed(agent, "match_hubspot_company")[0] is False
        if agent == "contracts_agent":
            assert is_tool_allowed(agent, "compare_sold_contracted_invoiced")[0] is True
        if agent == "reconciliation_agent":
            assert is_tool_allowed(agent, "match_hubspot_company")[0] is True
            assert is_tool_allowed(agent, "enrich_aging_hubspot")[0] is False


def test_hubspot_denied_on_coordinator_and_payments() -> None:
    for agent in ("finance_ops_coordinator", "payments_agent"):
        for tool in sorted(HUBSPOT_READ_TOOLS | HUBSPOT_WRITE_TOOLS):
            ok, reason = is_tool_allowed(agent, tool)
            assert ok is False, f"{agent}.{tool} should be denied"
            assert reason in {
                "hubspot_denied_for_agent",
                "tool_not_in_allowlist",
            }, reason


def test_hubspot_write_never_llm_allowlisted() -> None:
    for agent in (
        "invoice_agent",
        "contracts_agent",
        "reconciliation_agent",
        "finance_ops_coordinator",
        "payments_agent",
    ):
        for tool in sorted(HUBSPOT_WRITE_TOOLS):
            ok, reason = is_tool_allowed(agent, tool)
            assert ok is False, f"{agent}.{tool}"
            assert reason in {
                "hubspot_write_runtime_only",
                "hubspot_denied_for_agent",
                "tool_not_in_allowlist",
            }
