"""#5 Typed A2A — Pydantic state objects between coordinator and specialists."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    evidence_id: str
    sources: list[str] = Field(default_factory=list)


class AgentTask(BaseModel):
    """Typed handoff from coordinator → specialist (never raw free-text only)."""

    task_id: str
    target_agent: Literal[
        "invoice_agent",
        "payments_agent",
        "contracts_agent",
        "reconciliation_agent",
        "coordinator",
    ]
    intent: str
    entities: dict[str, str] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentResult(BaseModel):
    """Typed handoff from specialist → coordinator."""

    task_id: str
    agent: str
    status: Literal["ok", "needs_review", "error"]
    summary: str
    facts: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class SwarmState(BaseModel):
    """Shared typed swarm state (A2A bus)."""

    conversation_id: str
    tasks: list[AgentTask] = Field(default_factory=list)
    results: list[AgentResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def assign(self, task: AgentTask) -> None:
        self.tasks.append(task)

    def complete(self, result: AgentResult) -> None:
        self.results.append(result)

    def latest_for(self, agent: str) -> AgentResult | None:
        for result in reversed(self.results):
            if result.agent == agent:
                return result
        return None


def build_invoice_aging_task(conversation_id: str, customer_id: str) -> tuple[SwarmState, AgentTask]:
    import uuid

    state = SwarmState(conversation_id=conversation_id)
    task = AgentTask(
        task_id=f"TASK-{uuid.uuid4().hex[:8]}",
        target_agent="invoice_agent",
        intent="aging_summary",
        entities={"customer_id": customer_id},
        constraints=["cite_evidence_id", "no_invented_balances"],
    )
    state.assign(task)
    return state, task


def execute_typed_invoice_aging(task: AgentTask) -> AgentResult:
    """Deterministic specialist execution using typed task → typed result."""
    from finance_ops.tools.invoice_tools import aging_summary

    customer_id = task.entities.get("customer_id", "")
    raw = aging_summary(customer_id)
    evidence = []
    if raw.get("evidence", {}).get("evidence_id"):
        evidence.append(
            EvidenceRef(
                evidence_id=raw["evidence"]["evidence_id"],
                sources=[f"customer:{customer_id}"],
            )
        )
    status: Literal["ok", "needs_review", "error"] = (
        "needs_review" if raw.get("needs_review") else "ok"
    )
    if raw.get("status") not in {"success", "ok"}:
        status = "error"
    return AgentResult(
        task_id=task.task_id,
        agent="invoice_agent",
        status=status,
        summary=f"Open AR for {customer_id}: {raw.get('total_open')}",
        facts={
            "total_open": raw.get("total_open"),
            "buckets": raw.get("buckets"),
            "invoice_count": raw.get("invoice_count"),
        },
        evidence=evidence,
        next_actions=["review_past_due"] if (raw.get("total_open") or 0) > 0 else [],
    )
