"""Policy-as-code for approval / apply decisions — pure functions + YAML/env config."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from finance_ops.governance.audit import append_audit

Outcome = Literal["allow", "require_human", "deny"]

_DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "policy.yaml"


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason: str

    @property
    def allowed(self) -> bool:
        return self.outcome == "allow"

    @property
    def needs_human(self) -> bool:
        return self.outcome == "require_human"

    @property
    def denied(self) -> bool:
        return self.outcome == "deny"


class PolicyLoadError(RuntimeError):
    """Raised when policy config cannot be loaded — callers must fail closed."""


def _env_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return float(raw)


def policy_path() -> Path:
    override = os.getenv("FINANCE_OPS_POLICY_PATH", "").strip()
    return Path(override) if override else _DEFAULT_POLICY_PATH


@lru_cache(maxsize=4)
def load_policy(path_str: str | None = None) -> dict[str, Any]:
    """Load and cache policy YAML. Fail closed on missing/invalid config."""
    path = Path(path_str) if path_str else policy_path()
    if not path.is_file():
        raise PolicyLoadError(f"policy file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyLoadError(f"policy load failed: {exc}") from exc
    if not isinstance(data, dict) or "thresholds" not in data:
        raise PolicyLoadError("policy missing thresholds")
    thresholds = dict(data.get("thresholds") or {})
    # Env overrides (optional)
    for env_name, key in (
        ("FINANCE_OPS_POLICY_AUTO_ALLOW_MAX", "auto_allow_max"),
        ("FINANCE_OPS_POLICY_REQUIRE_HUMAN_ABOVE", "require_human_above"),
        ("FINANCE_OPS_POLICY_DENY_ABOVE", "deny_above"),
    ):
        val = _env_float(env_name)
        if val is not None:
            thresholds[key] = val
    data = {**data, "thresholds": thresholds}
    return data


def clear_policy_cache() -> None:
    load_policy.cache_clear()


def _action_default(policy: dict[str, Any], action: str) -> Outcome:
    actions = policy.get("actions") or {}
    entry = actions.get(action) or {}
    raw = (entry.get("default") if isinstance(entry, dict) else None) or "require_human"
    raw = str(raw).strip().lower()
    if raw not in {"allow", "require_human", "deny"}:
        return "require_human"
    return raw  # type: ignore[return-value]


def _vendor_risk_outcome(policy: dict[str, Any], vendor_risk: str) -> Outcome | None:
    risk = (vendor_risk or "unknown").strip().lower() or "unknown"
    mapping = policy.get("vendor_risk") or {}
    raw = mapping.get(risk)
    if raw is None:
        return None
    raw = str(raw).strip().lower()
    if raw not in {"allow", "require_human", "deny"}:
        return None
    return raw  # type: ignore[return-value]


def requires_approval(
    action: str,
    amount: float,
    vendor_risk: str = "unknown",
    *,
    audit: bool = True,
    agent: str = "policy",
) -> Decision:
    """Decide allow | require_human | deny for an action/amount/risk tuple.

    Fail closed: any load error → deny.
    """
    action_norm = (action or "").strip() or "unknown"
    try:
        amount_f = float(amount)
    except (TypeError, ValueError):
        decision = Decision("deny", "invalid_amount")
        if audit:
            append_audit(
                event="policy_decision",
                agent=agent,
                tool=action_norm,
                args={"amount": amount, "vendor_risk": vendor_risk},
                decision=decision.outcome,
                reason=decision.reason,
            )
        return decision

    try:
        policy = load_policy()
    except PolicyLoadError as exc:
        decision = Decision("deny", f"policy_unavailable:{exc}")
        if audit:
            append_audit(
                event="policy_decision",
                agent=agent,
                tool=action_norm,
                args={"amount": amount_f, "vendor_risk": vendor_risk},
                decision=decision.outcome,
                reason=decision.reason,
            )
        return decision

    thresholds = policy.get("thresholds") or {}
    try:
        deny_above = float(thresholds.get("deny_above", 1_000_000))
        require_above = float(thresholds.get("require_human_above", 0))
        auto_max = float(thresholds.get("auto_allow_max", 0))
    except (TypeError, ValueError):
        decision = Decision("deny", "invalid_thresholds")
        if audit:
            append_audit(
                event="policy_decision",
                agent=agent,
                tool=action_norm,
                args={"amount": amount_f, "vendor_risk": vendor_risk},
                decision=decision.outcome,
                reason=decision.reason,
            )
        return decision

    # 1) Hard deny by amount
    if amount_f > deny_above:
        decision = Decision("deny", f"amount_above_deny:{deny_above}")
    else:
        # 2) Vendor risk override
        risk_outcome = _vendor_risk_outcome(policy, vendor_risk)
        if risk_outcome == "deny":
            decision = Decision("deny", f"vendor_risk:{(vendor_risk or 'unknown').lower()}")
        elif risk_outcome == "require_human":
            decision = Decision(
                "require_human", f"vendor_risk:{(vendor_risk or 'unknown').lower()}"
            )
        elif amount_f > require_above:
            decision = Decision("require_human", f"amount_above_human:{require_above}")
        else:
            action_default = _action_default(policy, action_norm)
            if action_default == "deny":
                decision = Decision("deny", f"action_default:{action_norm}")
            elif action_default == "require_human":
                # Auto-allow only when action default is allow OR amount within auto band
                # and default is require_human but auto_allow_max covers it — still human
                # unless action default is allow.
                decision = Decision("require_human", f"action_default:{action_norm}")
            elif amount_f <= auto_max:
                decision = Decision("allow", f"auto_allow_max:{auto_max}")
            else:
                decision = Decision("require_human", f"above_auto_allow_max:{auto_max}")

    if audit:
        append_audit(
            event="policy_decision",
            agent=agent,
            tool=action_norm,
            args={"amount": amount_f, "vendor_risk": vendor_risk},
            decision=decision.outcome,
            reason=decision.reason,
        )
    return decision


def enforce_or_deny(
    action: str,
    amount: float,
    vendor_risk: str = "unknown",
    *,
    agent: str = "policy",
) -> dict[str, Any] | None:
    """Return an error dict if denied; None if allow or require_human (caller proceeds)."""
    decision = requires_approval(
        action, amount, vendor_risk=vendor_risk, agent=agent, audit=True
    )
    if decision.denied:
        return {
            "status": "denied",
            "error": "policy_denied",
            "policy": {
                "outcome": decision.outcome,
                "reason": decision.reason,
                "action": action,
                "amount": amount,
                "vendor_risk": vendor_risk,
            },
            "needs_review": True,
        }
    return None
