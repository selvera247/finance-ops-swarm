"""Agent tools for C3 shadow trajectories (propose only — no warehouse/HITL writes)."""

from __future__ import annotations

from typing import Any

from finance_ops.lib.evidence import record_evidence
from finance_ops.runtime.circuit_breaker import DEFAULT_BREAKER
from finance_ops.runtime.shadow import (
    DEFAULT_SHADOW,
    SPIKE_A_WALKTHROUGH,
    SPIKE_B_WALKTHROUGH,
    build_cash_app_shadow,
    build_spike_a_shadow_bundle,
    build_spike_b_shadow_bundle,
)


def _guard(tool_name: str) -> None:
    DEFAULT_BREAKER.record_tool(tool_name)


def shadow_cash_app_trajectory(payment_id: str, invoice_id: str = "") -> dict[str, Any]:
    """C3: suggest + propose HITL/apply for one payment without mutating state.

    Safe for demos — does not create approvals, Slack messages, or apply matches.
    """
    _guard("shadow_cash_app_trajectory")
    traj = build_cash_app_shadow(payment_id, invoice_id=invoice_id)
    result = {
        "status": "success",
        "mode": "shadow",
        "mutated": False,
        "trajectory": traj.model_dump(),
        "needs_review": True,
        "resume_hint": (
            "Shadow only. To execute for real: request_cash_app_approval then HITL decide."
        ),
    }
    result["evidence"] = record_evidence(
        agent="payments_agent",
        action="shadow_cash_app_trajectory",
        inputs={"payment_id": payment_id, "invoice_id": invoice_id or None},
        outputs={
            "trajectory_id": traj.trajectory_id,
            "would_mutate": traj.would_mutate,
            "steps": len(traj.steps),
        },
        sources=["shadow:cash_app", "policy:no_side_effects"],
    )
    return result


def shadow_spike_a_walkthrough() -> dict[str, Any]:
    """C3: shadow PAY-1001 / PAY-2001 / PAY-3001 in one bundle (no mutations)."""
    _guard("shadow_spike_a_walkthrough")
    bundle = build_spike_a_shadow_bundle(SPIKE_A_WALKTHROUGH)
    result = {
        "status": "success",
        "mode": "shadow",
        "mutated": False,
        "bundle": bundle,
        "needs_review": True,
    }
    result["evidence"] = record_evidence(
        agent="payments_agent",
        action="shadow_spike_a_walkthrough",
        inputs={"payment_ids": list(SPIKE_A_WALKTHROUGH)},
        outputs={
            "bundle_id": bundle.get("bundle_id"),
            "count": len(bundle.get("trajectories") or []),
        },
        sources=["shadow:spike_a", "policy:no_side_effects"],
    )
    return result


def shadow_spike_b_walkthrough() -> dict[str, Any]:
    """C3+Spike B: shadow CLM-B1001 / B2001 / B3001 without creating HITL."""
    _guard("shadow_spike_b_walkthrough")
    bundle = build_spike_b_shadow_bundle(SPIKE_B_WALKTHROUGH)
    result = {
        "status": "success",
        "mode": "shadow",
        "mutated": False,
        "bundle": bundle,
        "needs_review": True,
    }
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="shadow_spike_b_walkthrough",
        inputs={"claim_ids": list(SPIKE_B_WALKTHROUGH)},
        outputs={
            "bundle_id": bundle.get("bundle_id"),
            "count": len(bundle.get("trajectories") or []),
        },
        sources=["shadow:spike_b", "policy:no_side_effects"],
    )
    return result


def list_shadow_trajectories(limit: int = 20) -> dict[str, Any]:
    """List recent shadow trajectories from the warehouse shadow store."""
    _guard("list_shadow_trajectories")
    rows = [t.model_dump() for t in DEFAULT_SHADOW.list(limit=max(1, min(int(limit), 100)))]
    result = {
        "status": "success",
        "count": len(rows),
        "trajectories": rows,
        "needs_review": False,
    }
    result["evidence"] = record_evidence(
        agent="payments_agent",
        action="list_shadow_trajectories",
        inputs={"limit": limit},
        outputs={"count": len(rows)},
        sources=["shadow:store"],
    )
    return result


def get_shadow_trajectory(trajectory_id: str) -> dict[str, Any]:
    """Load one shadow trajectory by id (SHD-...)."""
    _guard("get_shadow_trajectory")
    traj = DEFAULT_SHADOW.get(trajectory_id.strip())
    if not traj:
        result: dict[str, Any] = {
            "status": "not_found",
            "trajectory_id": trajectory_id,
            "needs_review": True,
        }
    else:
        result = {
            "status": "success",
            "trajectory": traj.model_dump(),
            "needs_review": False,
        }
    result["evidence"] = record_evidence(
        agent="payments_agent",
        action="get_shadow_trajectory",
        inputs={"trajectory_id": trajectory_id},
        outputs={"status": result["status"]},
        sources=["shadow:store"],
    )
    return result
