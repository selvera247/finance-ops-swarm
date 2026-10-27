"""#1 Durable state-machine workflow (Temporal/LangGraph-shaped, file checkpoints).

Runs a multi-step portal extract → ingest → reconcile DAG with:
  - persisted checkpoints
  - exponential backoff retries
  - crash recovery via resume(run_id)
"""

from __future__ import annotations

import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from data_plane.config import WAREHOUSE_DIR, ensure_dirs


class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"


class WorkflowStep(BaseModel):
    name: str
    status: StepStatus = StepStatus.pending
    attempts: int = 0
    last_error: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None


class WorkflowState(BaseModel):
    run_id: str
    name: str = "portal_extract_reconcile"
    status: StepStatus = StepStatus.pending
    steps: list[WorkflowStep]
    created_at: str
    updated_at: str
    meta: dict[str, Any] = Field(default_factory=dict)


StepFn = Callable[[WorkflowState], dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DurableWorkflow:
    def __init__(self, root: Path | None = None) -> None:
        ensure_dirs()
        self.root = root or (WAREHOUSE_DIR / "workflows")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        return self.root / f"{run_id}.json"

    def save(self, state: WorkflowState) -> None:
        state.updated_at = _now()
        self._path(state.run_id).write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def load(self, run_id: str) -> WorkflowState:
        return WorkflowState.model_validate_json(self._path(run_id).read_text(encoding="utf-8"))

    def create(self, step_names: list[str], *, meta: dict[str, Any] | None = None) -> WorkflowState:
        state = WorkflowState(
            run_id=f"WF-{uuid.uuid4().hex[:10]}",
            steps=[WorkflowStep(name=n) for n in step_names],
            created_at=_now(),
            updated_at=_now(),
            meta=meta or {},
        )
        self.save(state)
        return state

    def run(
        self,
        handlers: dict[str, StepFn],
        *,
        state: WorkflowState | None = None,
        max_retries: int = 3,
        base_delay_seconds: float = 0.05,
    ) -> WorkflowState:
        if state is None:
            state = self.create(list(handlers.keys()))
        state.status = StepStatus.running
        self.save(state)

        for step in state.steps:
            if step.status == StepStatus.success:
                continue
            fn = handlers[step.name]
            while step.attempts < max_retries:
                step.attempts += 1
                step.status = StepStatus.running
                step.started_at = step.started_at or _now()
                step.last_error = None
                self.save(state)
                try:
                    step.output = fn(state) or {}
                    step.status = StepStatus.success
                    step.finished_at = _now()
                    self.save(state)
                    break
                except Exception as exc:  # noqa: BLE001
                    step.last_error = f"{exc}\n{traceback.format_exc(limit=3)}"
                    self.save(state)
                    if step.attempts >= max_retries:
                        step.status = StepStatus.failed
                        step.finished_at = _now()
                        state.status = StepStatus.failed
                        self.save(state)
                        return state
                    time.sleep(base_delay_seconds * (2 ** (step.attempts - 1)))

        if all(s.status == StepStatus.success for s in state.steps):
            state.status = StepStatus.success
        self.save(state)
        return state

    def resume(self, run_id: str, handlers: dict[str, StepFn], **kwargs: Any) -> WorkflowState:
        state = self.load(run_id)
        return self.run(handlers, state=state, **kwargs)

    def signal(self, run_id: str, name: str, payload: dict[str, Any] | None = None) -> WorkflowState:
        """Temporal-shaped external signal (e.g. HITL approved) persisted on meta."""
        state = self.load(run_id)
        signals = list(state.meta.get("signals") or [])
        signals.append({"name": name, "payload": payload or {}, "at": _now()})
        state.meta["signals"] = signals
        state.meta[f"signal_{name}"] = payload or {"ok": True}
        self.save(state)
        return state


def portal_reconcile_handlers() -> dict[str, StepFn]:
    """Default DAG: ensure warehouse → process incoming → fallback resolve → smoke match."""

    def step_batch(state: WorkflowState) -> dict[str, Any]:
        from pipelines.batch.ingest import ingest_batch

        return ingest_batch(run_id=f"wf-batch-{state.run_id}")

    def step_incoming(state: WorkflowState) -> dict[str, Any]:
        from gui_connectors.ingest.portal_ingest import process_incoming

        return process_incoming()

    def step_resolve(state: WorkflowState) -> dict[str, Any]:
        from finance_ops.runtime.fallback_router import resolve_portal_data

        return resolve_portal_data(
            "legacy_bank",
            extract_type="bank_statement",
            min_rows=1,
            allow_browser_fallback=bool(state.meta.get("allow_browser", True)),
        )

    def step_reconcile_smoke(state: WorkflowState) -> dict[str, Any]:
        from finance_ops.tools.payment_tools import suggest_payment_match

        return suggest_payment_match("PAY-9002")

    return {
        "batch_ingest": step_batch,
        "process_incoming": step_incoming,
        "resolve_portal": step_resolve,
        "reconcile_smoke": step_reconcile_smoke,
    }


def deal_closed_won_handlers() -> dict[str, StepFn]:
    """D7 DAG keyed by HubSpot deal id: fetch deal → line items → flag review."""

    def step_fetch_deal(state: WorkflowState) -> dict[str, Any]:
        from finance_ops.tools.hubspot_tools import get_deal

        deal_id = str(state.meta.get("hubspot_deal_id") or "")
        out = get_deal(deal_id)
        if out.get("status") != "success":
            raise RuntimeError(out.get("error") or "hubspot_get_deal_failed")
        state.meta["deal"] = out.get("deal") or {}
        return {"deal_id": deal_id, "status": out.get("status")}

    def step_line_items(state: WorkflowState) -> dict[str, Any]:
        from finance_ops.tools.hubspot_tools import get_deal_line_items

        deal_id = str(state.meta.get("hubspot_deal_id") or "")
        out = get_deal_line_items(deal_id)
        if out.get("status") not in {"success", "denied"}:
            # denied (no token) soft-records; other errors retry
            if out.get("status") == "error":
                raise RuntimeError(out.get("error") or "line_items_failed")
        state.meta["line_items"] = out.get("line_items") or []
        return {"count": out.get("count", 0), "status": out.get("status")}

    def step_flag_review(state: WorkflowState) -> dict[str, Any]:
        deal = state.meta.get("deal") or {}
        props = deal.get("properties") if isinstance(deal, dict) else {}
        amount = props.get("amount") if isinstance(props, dict) else None
        return {
            "needs_review": True,
            "reason": "hubspot_deal_closed_won_review",
            "deal_id": state.meta.get("hubspot_deal_id"),
            "amount": amount,
            "line_item_count": len(state.meta.get("line_items") or []),
        }

    return {
        "fetch_deal": step_fetch_deal,
        "fetch_line_items": step_line_items,
        "flag_review": step_flag_review,
    }
