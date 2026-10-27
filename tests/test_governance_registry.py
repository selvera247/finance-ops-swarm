"""D3 agent registry lifecycle — TTL retire, eval deprecate, refusal, sweep."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from finance_ops.governance import rbac
from finance_ops.governance.callbacks import before_agent_registry, before_tool_rbac
from finance_ops.governance.rbac import is_tool_allowed
from finance_ops.governance.registry import (
    evaluate_lifecycle,
    get_agent,
    is_invocation_allowed,
    load_registry,
    set_eval_score,
    set_status,
    state_path,
    sweep_lifecycle,
    touch_last_run,
)


@pytest.fixture()
def registry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    seed = tmp_path / "registry.yaml"
    seed.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "default_ttl_days": 90,
                "default_eval_threshold": 0.8,
                "agents": [
                    {
                        "name": "invoice_agent",
                        "owner": "test",
                        "ttl_days": 30,
                        "eval_threshold": 0.8,
                        "status": "active",
                        "latest_eval_score": 1.0,
                    },
                    {
                        "name": "payments_agent",
                        "owner": "test",
                        "ttl_days": 90,
                        "eval_threshold": 0.8,
                        "status": "active",
                        "latest_eval_score": 1.0,
                    },
                    {
                        "name": "finance_ops_coordinator",
                        "owner": "test",
                        "ttl_days": 90,
                        "status": "active",
                        "latest_eval_score": 1.0,
                    },
                    {
                        "name": "contracts_agent",
                        "owner": "test",
                        "ttl_days": 90,
                        "status": "active",
                        "latest_eval_score": 1.0,
                    },
                    {
                        "name": "reconciliation_agent",
                        "owner": "test",
                        "ttl_days": 180,
                        "status": "active",
                        "latest_eval_score": 1.0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FINANCE_OPS_REGISTRY_PATH", str(seed))
    monkeypatch.setattr(
        "finance_ops.governance.registry.WAREHOUSE_DIR",
        tmp_path / "wh",
    )
    # snapshot allowlists so revoke tests don't poison later suites
    snapshot = {k: frozenset(v) for k, v in rbac.AGENT_TOOL_POLICY.items()}
    yield seed
    rbac.AGENT_TOOL_POLICY.clear()
    rbac.AGENT_TOOL_POLICY.update(snapshot)


def test_touch_last_run(registry_env: Path) -> None:
    _ = registry_env
    rec = touch_last_run("invoice_agent")
    assert rec is not None
    assert rec.last_run_at
    assert state_path().is_file()


def test_ttl_retire_and_revoke(registry_env: Path) -> None:
    _ = registry_env
    agents = load_registry()
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    agents["invoice_agent"].last_run_at = old
    from finance_ops.governance.registry import save_registry

    save_registry(agents)
    assert evaluate_lifecycle(agents["invoice_agent"]) == "retired"
    out = sweep_lifecycle()
    assert out["status"] == "success"
    assert any(t["agent"] == "invoice_agent" and t["to"] == "retired" for t in out["transitions"])
    rec = get_agent("invoice_agent")
    assert rec is not None
    assert rec.status == "retired"
    assert rec.credentials_revoked is True
    assert rbac.AGENT_TOOL_POLICY.get("invoice_agent") == frozenset()
    ok, reason = is_invocation_allowed("invoice_agent")
    assert ok is False
    assert reason == "agent_retired"


def test_eval_score_deprecates(registry_env: Path) -> None:
    _ = registry_env
    touch_last_run("payments_agent")
    set_eval_score("payments_agent", 0.2)
    agents = load_registry()
    assert evaluate_lifecycle(agents["payments_agent"]) == "deprecated"
    out = sweep_lifecycle()
    assert any(t["agent"] == "payments_agent" and t["to"] == "deprecated" for t in out["transitions"])


def test_before_agent_refuses_retired(registry_env: Path) -> None:
    _ = registry_env
    set_status("invoice_agent", "retired", reason="test")
    ctx = SimpleNamespace(agent_name="invoice_agent")
    blocked = before_agent_registry(ctx)
    assert blocked is not None


def test_tool_denied_when_retired(registry_env: Path) -> None:
    _ = registry_env
    set_status("invoice_agent", "retired", reason="test")
    ok, reason = is_tool_allowed("invoice_agent", "aging_summary")
    assert ok is False
    assert reason == "agent_retired"
    out = before_tool_rbac(
        SimpleNamespace(name="aging_summary"),
        {},
        SimpleNamespace(agent_name="invoice_agent"),
    )
    assert out is not None
    assert out["status"] == "denied"


def test_reconciliation_longer_ttl(registry_env: Path) -> None:
    _ = registry_env
    agents = load_registry()
    # 100 days idle — still active for 180d TTL
    agents["reconciliation_agent"].last_run_at = (
        datetime.now(timezone.utc) - timedelta(days=100)
    ).isoformat()
    assert evaluate_lifecycle(agents["reconciliation_agent"]) == "active"


def test_agents_have_lifecycle_callbacks() -> None:
    from finance_ops.agent import root_agent
    from finance_ops.governance.callbacks import after_agent_registry, before_agent_registry
    from finance_ops.specialists.invoice_agent import invoice_agent

    assert root_agent.before_agent_callback is before_agent_registry
    assert root_agent.after_agent_callback is after_agent_registry
    assert invoice_agent.before_agent_callback is before_agent_registry


def test_fail_closed_missing_registry_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FINANCE_OPS_REGISTRY_PATH", str(tmp_path / "missing.yaml"))
    monkeypatch.setattr(
        "finance_ops.governance.registry.WAREHOUSE_DIR",
        tmp_path / "wh",
    )
    ok, reason = is_invocation_allowed("invoice_agent")
    assert ok is False
    assert "registry_unavailable" in reason


def test_fail_closed_corrupt_registry_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = tmp_path / "registry.yaml"
    seed.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "agents": [{"name": "invoice_agent", "owner": "t", "status": "active"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FINANCE_OPS_REGISTRY_PATH", str(seed))
    wh = tmp_path / "wh"
    monkeypatch.setattr("finance_ops.governance.registry.WAREHOUSE_DIR", wh)
    # Prime a valid state, then corrupt it
    load_registry()
    state_path().write_text("{not-json", encoding="utf-8")
    ok, reason = is_invocation_allowed("invoice_agent")
    assert ok is False
    assert "registry_unavailable" in reason


def test_sweep_http_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from finance_ops.serving import app

    client = TestClient(app)
    monkeypatch.delenv("FINANCE_OPS_GOVERNANCE_TOKEN", raising=False)
    assert client.post("/v1/governance/sweep").status_code == 503

    monkeypatch.setenv("FINANCE_OPS_GOVERNANCE_TOKEN", "secret-sweep-token")
    assert client.post("/v1/governance/sweep").status_code == 401
    ok = client.post(
        "/v1/governance/sweep",
        headers={"X-Governance-Token": "secret-sweep-token"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "success"
