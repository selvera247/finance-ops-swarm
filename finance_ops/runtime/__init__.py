"""Production agent runtime primitives: breaker, fallback, HITL, durable DAG, typed A2A."""

from finance_ops.runtime.a2a import AgentResult, AgentTask, SwarmState
from finance_ops.runtime.circuit_breaker import CircuitBreaker, CircuitOpenError
from finance_ops.runtime.durable import DurableWorkflow
from finance_ops.runtime.fallback_router import resolve_portal_data
from finance_ops.runtime.hitl import ApprovalStore, PendingApproval
from finance_ops.runtime.slack_hitl import notify_slack

__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "resolve_portal_data",
    "ApprovalStore",
    "PendingApproval",
    "DurableWorkflow",
    "AgentTask",
    "AgentResult",
    "SwarmState",
    "notify_slack",
]
