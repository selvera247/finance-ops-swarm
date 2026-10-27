"""C3 Shadow trajectories — record what the agent *would* do without side effects.

Reads (e.g. suggest_payment_match) may run. Mutative tools (HITL create, apply match,
Slack notify, portal browser) are **proposed only** and never executed.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from data_plane.config import WAREHOUSE_DIR, ensure_dirs

SideEffect = Literal["none", "shadow_skipped", "read_ok"]


class ShadowStep(BaseModel):
    seq: int
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    side_effect: SideEffect = "none"
    status: str = "proposed"
    summary: str = ""
    outputs: dict[str, Any] = Field(default_factory=dict)


class ShadowTrajectory(BaseModel):
    trajectory_id: str
    kind: str = "cash_app"
    status: Literal["open", "closed"] = "open"
    created_at: str
    updated_at: str
    meta: dict[str, Any] = Field(default_factory=dict)
    steps: list[ShadowStep] = Field(default_factory=list)
    would_mutate: bool = False
    notes: list[str] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ShadowStore:
    def __init__(self, root: Path | None = None) -> None:
        ensure_dirs()
        self.root = root or (WAREHOUSE_DIR / "shadow")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, trajectory_id: str) -> Path:
        return self.root / f"{trajectory_id}.json"

    def save(self, traj: ShadowTrajectory) -> None:
        traj.updated_at = _now()
        self._path(traj.trajectory_id).write_text(
            traj.model_dump_json(indent=2), encoding="utf-8"
        )

    def get(self, trajectory_id: str) -> ShadowTrajectory | None:
        path = self._path(trajectory_id)
        if not path.exists():
            return None
        return ShadowTrajectory.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, limit: int = 20) -> list[ShadowTrajectory]:
        files = sorted(self.root.glob("SHD-*.json"), reverse=True)
        return [
            ShadowTrajectory.model_validate_json(p.read_text(encoding="utf-8"))
            for p in files[:limit]
        ]

    def create(self, *, kind: str, meta: dict[str, Any] | None = None) -> ShadowTrajectory:
        traj = ShadowTrajectory(
            trajectory_id=f"SHD-{uuid.uuid4().hex[:10]}",
            kind=kind,
            created_at=_now(),
            updated_at=_now(),
            meta=meta or {},
        )
        self.save(traj)
        return traj

    def append(
        self,
        trajectory_id: str,
        *,
        tool: str,
        args: dict[str, Any] | None = None,
        side_effect: SideEffect = "shadow_skipped",
        status: str = "proposed",
        summary: str = "",
        outputs: dict[str, Any] | None = None,
    ) -> ShadowTrajectory:
        traj = self.get(trajectory_id)
        if traj is None:
            raise KeyError(trajectory_id)
        step = ShadowStep(
            seq=len(traj.steps) + 1,
            tool=tool,
            args=args or {},
            side_effect=side_effect,
            status=status,
            summary=summary,
            outputs=outputs or {},
        )
        traj.steps.append(step)
        if side_effect == "shadow_skipped":
            traj.would_mutate = True
        self.save(traj)
        return traj

    def close(self, trajectory_id: str, *, note: str | None = None) -> ShadowTrajectory:
        traj = self.get(trajectory_id)
        if traj is None:
            raise KeyError(trajectory_id)
        traj.status = "closed"
        if note:
            traj.notes.append(note)
        self.save(traj)
        return traj


DEFAULT_SHADOW = ShadowStore()


def predict_apply_outcome(payment_id: str, invoice_id: str) -> dict[str, Any]:
    """Same checks as apply_payment_match without writing."""
    from data_plane import repository as repo

    payment_id = payment_id.strip().upper()
    invoice_id = invoice_id.strip().upper()
    payment = repo.get_payment(payment_id)
    if not payment:
        return {"ok": False, "error": "payment_not_found", "payment_id": payment_id}
    invoice = repo.get_invoice(invoice_id)
    if not invoice:
        return {"ok": False, "error": "invoice_not_found", "invoice_id": invoice_id}
    if str(payment.get("customer_id")) != str(invoice.get("customer_id")):
        return {
            "ok": False,
            "error": "customer_mismatch",
            "payment_customer": payment.get("customer_id"),
            "invoice_customer": invoice.get("customer_id"),
        }
    return {
        "ok": True,
        "payment_id": payment_id,
        "invoice_id": invoice_id,
        "would_set": {"status": "matched", "matched_invoice_id": invoice_id},
        "payment_amount": payment.get("amount"),
        "invoice_amount": invoice.get("amount"),
        "current_payment_status": payment.get("status"),
    }


def build_cash_app_shadow(
    payment_id: str,
    invoice_id: str = "",
    *,
    store: ShadowStore | None = None,
) -> ShadowTrajectory:
    """Read suggest → propose HITL + apply. Never creates approvals or mutates warehouse."""
    from finance_ops.tools.payment_tools import suggest_payment_match

    store = store or DEFAULT_SHADOW
    payment_id = payment_id.strip().upper()
    traj = store.create(
        kind="cash_app",
        meta={"payment_id": payment_id, "mode": "shadow"},
    )

    suggestion = suggest_payment_match(payment_id)
    store.append(
        traj.trajectory_id,
        tool="suggest_payment_match",
        args={"payment_id": payment_id},
        side_effect="read_ok",
        status=suggestion.get("status", "unknown"),
        summary=(
            f"recommendation={suggestion.get('recommendation')} "
            f"candidates={len(suggestion.get('candidates') or [])}"
        ),
        outputs={
            "recommendation": suggestion.get("recommendation"),
            "candidates": suggestion.get("candidates"),
            "needs_review": suggestion.get("needs_review"),
            "payment_status": (suggestion.get("payment") or {}).get("status"),
        },
    )

    if suggestion.get("status") != "success":
        traj = store.close(traj.trajectory_id, note="suggest failed; no mutate proposals")
        return traj

    invoice_id = (invoice_id or suggestion.get("recommendation") or "").strip().upper()
    payment = suggestion.get("payment") or {}
    amount = float(payment.get("amount") or 0)

    if not invoice_id:
        kind = "cash_app_escalate"
        summary = f"Cash app escalate: {payment_id} — no invoice candidates"
        payload = {
            "payment_id": payment_id,
            "invoice_id": None,
            "candidates": suggestion.get("candidates") or [],
        }
    else:
        kind = "cash_app_match"
        summary = f"Cash app match: {payment_id} → {invoice_id}"
        payload = {
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "recommended_invoice_id": suggestion.get("recommendation"),
            "candidates": suggestion.get("candidates") or [],
        }

    store.append(
        traj.trajectory_id,
        tool="request_cash_app_approval",
        args={"payment_id": payment_id, "invoice_id": invoice_id or None, "notify_slack": True},
        side_effect="shadow_skipped",
        status="proposed",
        summary=f"would create HITL kind={kind} amount={amount}",
        outputs={
            "would_create_approval": {
                "kind": kind,
                "amount": amount,
                "summary": summary,
                "payload": payload,
            },
            "would_notify_slack": True,
        },
    )

    if invoice_id:
        predicted = predict_apply_outcome(payment_id, invoice_id)
        store.append(
            traj.trajectory_id,
            tool="apply_payment_match",
            args={"payment_id": payment_id, "invoice_id": invoice_id},
            side_effect="shadow_skipped",
            status="proposed" if predicted.get("ok") else "would_fail",
            summary=(
                "would apply match on HITL approve"
                if predicted.get("ok")
                else f"would fail: {predicted.get('error')}"
            ),
            outputs={"predict": predicted},
        )
    else:
        store.append(
            traj.trajectory_id,
            tool="apply_payment_match",
            args={"payment_id": payment_id},
            side_effect="shadow_skipped",
            status="skipped",
            summary="no invoice — apply not proposed",
            outputs={},
        )

    return store.close(
        traj.trajectory_id,
        note="shadow complete — warehouse and HITL unchanged",
    )


SPIKE_A_WALKTHROUGH = ("PAY-1001", "PAY-2001", "PAY-3001")
SPIKE_B_WALKTHROUGH = ("CLM-B1001", "CLM-B2001", "CLM-B3001")


def build_portal_extract_shadow(
    claim_id: str,
    *,
    store: ShadowStore | None = None,
) -> ShadowTrajectory:
    """Read classify → propose HITL review. Never creates approvals."""
    from finance_ops.tools.portal_spike_tools import classify_portal_exception

    store = store or DEFAULT_SHADOW
    claim_id = claim_id.strip().upper()
    traj = store.create(kind="portal_extract", meta={"claim_id": claim_id, "mode": "shadow"})

    classified = classify_portal_exception(claim_id)
    store.append(
        traj.trajectory_id,
        tool="classify_portal_exception",
        args={"claim_id": claim_id},
        side_effect="read_ok",
        status=classified.get("status", "unknown"),
        summary=(
            f"disposition={classified.get('disposition')} "
            f"kind={classified.get('hitl_kind')}"
        ),
        outputs={
            "disposition": classified.get("disposition"),
            "hitl_kind": classified.get("hitl_kind"),
            "suggested_invoice_ids": classified.get("suggested_invoice_ids"),
            "amount": classified.get("amount"),
        },
    )
    if classified.get("status") != "success":
        return store.close(traj.trajectory_id, note="classify failed; no HITL proposal")

    store.append(
        traj.trajectory_id,
        tool="request_portal_extract_review",
        args={"claim_id": claim_id, "notify_slack": True},
        side_effect="shadow_skipped",
        status="proposed",
        summary=f"would create HITL kind={classified.get('hitl_kind')}",
        outputs={
            "would_create_approval": {
                "kind": classified.get("hitl_kind"),
                "amount": classified.get("amount"),
                "summary": f"Portal extract {claim_id}: {classified.get('disposition')}",
                "payload": {
                    "claim_id": claim_id,
                    "disposition": classified.get("disposition"),
                    "suggested_invoice_ids": classified.get("suggested_invoice_ids"),
                },
            }
        },
    )
    return store.close(traj.trajectory_id, note="shadow complete — HITL unchanged")


def build_spike_b_shadow_bundle(
    claim_ids: tuple[str, ...] | list[str] = SPIKE_B_WALKTHROUGH,
    *,
    store: ShadowStore | None = None,
) -> dict[str, Any]:
    store = store or DEFAULT_SHADOW
    bundle_id = f"SHB-{uuid.uuid4().hex[:10]}"
    children: list[dict[str, Any]] = []
    for cid in claim_ids:
        traj = build_portal_extract_shadow(cid, store=store)
        children.append(
            {
                "claim_id": cid,
                "trajectory_id": traj.trajectory_id,
                "would_mutate": traj.would_mutate,
                "steps": len(traj.steps),
                "disposition": next(
                    (
                        s.outputs.get("disposition")
                        for s in traj.steps
                        if s.tool == "classify_portal_exception"
                    ),
                    None,
                ),
            }
        )
    bundle = {
        "bundle_id": bundle_id,
        "kind": "spike_b_walkthrough",
        "created_at": _now(),
        "trajectories": children,
        "mutated": False,
    }
    path = store.root / f"{bundle_id}.json"
    path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    bundle["path"] = str(path)
    return bundle



def build_spike_a_shadow_bundle(
    payment_ids: tuple[str, ...] | list[str] = SPIKE_A_WALKTHROUGH,
    *,
    store: ShadowStore | None = None,
) -> dict[str, Any]:
    store = store or DEFAULT_SHADOW
    bundle_id = f"SHB-{uuid.uuid4().hex[:10]}"
    children: list[dict[str, Any]] = []
    for pid in payment_ids:
        traj = build_cash_app_shadow(pid, store=store)
        children.append(
            {
                "payment_id": pid,
                "trajectory_id": traj.trajectory_id,
                "would_mutate": traj.would_mutate,
                "steps": len(traj.steps),
                "recommendation": next(
                    (
                        s.outputs.get("recommendation")
                        for s in traj.steps
                        if s.tool == "suggest_payment_match"
                    ),
                    None,
                ),
            }
        )
    bundle = {
        "bundle_id": bundle_id,
        "kind": "spike_a_walkthrough",
        "created_at": _now(),
        "trajectories": children,
        "mutated": False,
    }
    path = (store.root / f"{bundle_id}.json")
    path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    bundle["path"] = str(path)
    return bundle
