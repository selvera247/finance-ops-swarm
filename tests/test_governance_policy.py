"""D2 governance policy-as-code — thresholds, fail-closed, tool wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from finance_ops.governance import policy as policy_mod
from finance_ops.governance.policy import clear_policy_cache, requires_approval
from finance_ops.tools.payment_tools import apply_payment_match
from finance_ops.tools.runtime_tools import request_approval


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_policy_cache()
    yield
    clear_policy_cache()


def _write_policy(path: Path, **threshold_overrides: float) -> None:
    data = {
        "version": 1,
        "thresholds": {
            "auto_allow_max": 100.0,
            "require_human_above": 500.0,
            "deny_above": 10_000.0,
            **threshold_overrides,
        },
        "vendor_risk": {
            "high": "deny",
            "medium": "require_human",
            "low": None,
            "unknown": "require_human",
        },
        "actions": {
            "apply_payment_match": {"default": "allow"},
            "request_approval": {"default": "require_human"},
            "write_off": {"default": "require_human"},
            "cash_app_match": {"default": "require_human"},
        },
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_default_policy_loads() -> None:
    d = requires_approval("write_off", 125.0, vendor_risk="low", audit=False)
    # require_human_above default 0 → any positive amount needs human
    assert d.outcome == "require_human"


def test_deny_above_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "policy.yaml"
    _write_policy(path)
    monkeypatch.setenv("FINANCE_OPS_POLICY_PATH", str(path))
    clear_policy_cache()
    d = requires_approval("write_off", 10_000.01, vendor_risk="low", audit=False)
    assert d.denied
    assert "deny" in d.reason


def test_require_human_band(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "policy.yaml"
    _write_policy(path)
    monkeypatch.setenv("FINANCE_OPS_POLICY_PATH", str(path))
    clear_policy_cache()
    d = requires_approval("write_off", 750.0, vendor_risk="low", audit=False)
    assert d.needs_human


def test_auto_allow_when_action_allows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "policy.yaml"
    _write_policy(path)
    monkeypatch.setenv("FINANCE_OPS_POLICY_PATH", str(path))
    clear_policy_cache()
    # amount <= auto_allow_max and <= require_human_above, action default allow, risk low
    d = requires_approval("apply_payment_match", 50.0, vendor_risk="low", audit=False)
    assert d.allowed


def test_high_vendor_risk_denies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "policy.yaml"
    _write_policy(path)
    monkeypatch.setenv("FINANCE_OPS_POLICY_PATH", str(path))
    clear_policy_cache()
    d = requires_approval("write_off", 10.0, vendor_risk="high", audit=False)
    assert d.denied


def test_fail_closed_missing_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_POLICY_PATH", str(tmp_path / "missing.yaml"))
    clear_policy_cache()
    d = requires_approval("write_off", 1.0, audit=False)
    assert d.denied
    assert "policy_unavailable" in d.reason


def test_fail_closed_corrupt_policy_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("thresholds: [\n  this is not valid: [", encoding="utf-8")
    monkeypatch.setenv("FINANCE_OPS_POLICY_PATH", str(path))
    clear_policy_cache()
    d = requires_approval("write_off", 1.0, audit=False)
    assert d.denied
    assert "policy_unavailable" in d.reason


def test_env_override_deny_above(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "policy.yaml"
    _write_policy(path, deny_above=1_000_000)
    monkeypatch.setenv("FINANCE_OPS_POLICY_PATH", str(path))
    monkeypatch.setenv("FINANCE_OPS_POLICY_DENY_ABOVE", "50")
    clear_policy_cache()
    d = requires_approval("write_off", 51.0, vendor_risk="low", audit=False)
    assert d.denied


def test_request_approval_respects_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "policy.yaml"
    _write_policy(path, deny_above=100)
    monkeypatch.setenv("FINANCE_OPS_POLICY_PATH", str(path))
    clear_policy_cache()
    out = request_approval(
        kind="write_off",
        amount=500,
        summary="too large",
        notify_slack=False,
        vendor_risk="low",
    )
    assert out["status"] == "denied"
    assert out["policy"]["outcome"] == "deny"


def test_apply_payment_match_blocked_without_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default shipped policy: apply requires human — cannot bypass via direct apply."""
    # Use real default policy file (require_human for apply)
    monkeypatch.delenv("FINANCE_OPS_POLICY_PATH", raising=False)
    clear_policy_cache()
    out = apply_payment_match("PAY-1001", "INV-84219")
    assert out["status"] in {"needs_approval", "denied", "not_found", "error"}
    if out["status"] == "needs_approval":
        assert out["policy"]["outcome"] == "require_human"
        assert "request_cash_app_approval" in (out.get("hint") or "")
