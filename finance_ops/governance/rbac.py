"""Declarative tool RBAC — agent name → allowed tool names (deny by default).

Fail closed: unknown agents and missing policy entries are denied.
"""

from __future__ import annotations

from typing import Mapping

# Tools that mutate approvals or apply cash — never on the coordinator.
APPROVAL_MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "request_approval",
        "decide_approval",
        "request_cash_app_approval",
        "request_portal_extract_review",
        "apply_payment_match",
    }
)

PAYMENT_TOOLS: frozenset[str] = frozenset(
    {
        "lookup_payment",
        "list_unmatched_payments",
        "suggest_payment_match",
        "request_cash_app_approval",
        "apply_payment_match",
        "heal_suggest_payment",
    }
)

# HubSpot tool groups (deny by default — only listed agents get these names).
HUBSPOT_READ_TOOLS: frozenset[str] = frozenset(
    {
        "get_company",
        "get_deal",
        "list_closed_won_deals",
        "get_deal_line_items",
        "get_open_tickets_for_company",
        "compare_sold_contracted_invoiced",
        "enrich_aging_hubspot",
        "match_hubspot_company",
    }
)
HUBSPOT_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "create_task",
        "create_note",
    }
)

# Deny-by-default allowlists. Keep coordinator to route/read (+ non-payment portal ops).
AGENT_TOOL_POLICY: dict[str, frozenset[str]] = {
    "finance_ops_coordinator": frozenset(
        {
            # evidence / policy / read
            "search_policies",
            "flag_for_human_review",
            "get_evidence",
            "recent_evidence",
            "bigquery_status",
            # portal read + resolve (existing coordinator ownership; not payment apply)
            "fetch_legacy_bank_statement",
            "process_portal_incoming",
            "list_portal_extracts",
            "list_bank_statements",
            "classify_portal_exception",
            "spike_b_walkthrough",
            "resolve_portal_with_fallback",
            # HITL read-only
            "list_pending_approvals",
            "get_approval",
            # durable / a2a / circuit (ops; not payment match apply)
            "start_durable_reconcile",
            "resume_durable_workflow",
            "get_workflow_status",
            "run_typed_a2a_aging",
            "circuit_status",
            "reset_circuit_breaker",
            # sandbox / shadow / memory / craft (non-mutating payment apply)
            "run_sandboxed_calc",
            "run_sandboxed_python",
            "sandbox_status",
            "shadow_cash_app_trajectory",
            "shadow_spike_a_walkthrough",
            "shadow_spike_b_walkthrough",
            "list_shadow_trajectories",
            "get_shadow_trajectory",
            "memory_put",
            "memory_get",
            "memory_search",
            "memory_list",
            "memory_promote",
            "memory_evict",
            "memory_status",
            "budget_pack_context",
            "sanitize_payload",
            "heal_tool_result",
            # HubSpot: neither read nor write on coordinator
        }
    ),
    "invoice_agent": frozenset(
        {
            "lookup_invoice",
            "list_open_invoices",
            "aging_summary",
            "lookup_customer_risk",
            # HubSpot reads used for aging enrichment (D4); compare/match unused here
            "get_company",
            "get_deal",
            "list_closed_won_deals",
            "get_deal_line_items",
            "get_open_tickets_for_company",
            "enrich_aging_hubspot",
        }
    ),
    "payments_agent": frozenset(
        {
            "lookup_payment",
            "list_unmatched_payments",
            "suggest_payment_match",
            "request_cash_app_approval",
            "apply_payment_match",
            "request_approval",
            "decide_approval",
            "get_approval",
            "list_pending_approvals",
            "run_sandboxed_calc",
            "run_sandboxed_python",
            "shadow_cash_app_trajectory",
            "shadow_spike_a_walkthrough",
            "list_shadow_trajectories",
            "get_shadow_trajectory",
            "memory_put",
            "memory_get",
            "memory_search",
            "memory_promote",
            "budget_pack_context",
            "heal_suggest_payment",
            "heal_tool_result",
            # HubSpot: neither read nor write on payments (HITL write is runtime helper)
        }
    ),
    "contracts_agent": frozenset(
        {
            "lookup_contract",
            "lookup_customer_contract",
            "get_company",
            "get_deal",
            "list_closed_won_deals",
            "get_deal_line_items",
            "get_open_tickets_for_company",
            "compare_sold_contracted_invoiced",
        }
    ),
    "reconciliation_agent": frozenset(
        {
            "get_entity",
            "graph_neighborhood",
            "graph_status",
            "search_policies",
            "suggest_payment_match",
            "get_company",
            "get_deal",
            "list_closed_won_deals",
            "get_deal_line_items",
            "get_open_tickets_for_company",
            "match_hubspot_company",
        }
    ),
}


class PolicyLoadError(RuntimeError):
    """Raised when the RBAC policy cannot be used (fail closed)."""


def _policy() -> Mapping[str, frozenset[str]]:
    if not AGENT_TOOL_POLICY:
        raise PolicyLoadError("RBAC policy is empty")
    return AGENT_TOOL_POLICY


def allowed_tools_for(agent_name: str) -> frozenset[str]:
    """Return the allowlist for an agent; empty frozenset if unknown (deny all)."""
    try:
        policy = _policy()
    except PolicyLoadError:
        return frozenset()
    return policy.get(agent_name.strip(), frozenset())


def is_tool_allowed(agent_name: str, tool_name: str) -> tuple[bool, str]:
    """Return (allowed, reason). Fail closed on blank names or unknown agents."""
    agent = (agent_name or "").strip()
    tool = (tool_name or "").strip()
    if not agent or not tool:
        return False, "missing_agent_or_tool"
    # Lifecycle gate (retired / revoked grants)
    try:
        from finance_ops.governance.registry import is_invocation_allowed

        life_ok, life_reason = is_invocation_allowed(agent)
        if not life_ok:
            return False, life_reason
    except Exception as exc:  # noqa: BLE001
        return False, f"registry_error:{exc}"
    try:
        policy = _policy()
    except PolicyLoadError as exc:
        return False, f"policy_unavailable:{exc}"
    if agent not in policy:
        return False, "unknown_agent"
    allowed = policy[agent]
    if tool not in allowed:
        # Extra guard: coordinator never gets approval/payment mutators even if misconfigured
        if agent == "finance_ops_coordinator" and (
            tool in APPROVAL_MUTATING_TOOLS or tool in PAYMENT_TOOLS
        ):
            return False, "coordinator_denied_payment_or_approval_mutating"
        if agent in {"finance_ops_coordinator", "payments_agent"} and (
            tool in HUBSPOT_READ_TOOLS or tool in HUBSPOT_WRITE_TOOLS
        ):
            return False, "hubspot_denied_for_agent"
        return False, "tool_not_in_allowlist"
    if agent == "finance_ops_coordinator" and (
        tool in APPROVAL_MUTATING_TOOLS or tool in PAYMENT_TOOLS
    ):
        return False, "coordinator_denied_payment_or_approval_mutating"
    if agent in {"finance_ops_coordinator", "payments_agent"} and (
        tool in HUBSPOT_READ_TOOLS or tool in HUBSPOT_WRITE_TOOLS
    ):
        return False, "hubspot_denied_for_agent"
    # Write tools are never LLM-allowlisted; deny even if mis-added to a specialist
    if tool in HUBSPOT_WRITE_TOOLS and agent in {
        "invoice_agent",
        "contracts_agent",
        "reconciliation_agent",
        "finance_ops_coordinator",
        "payments_agent",
    }:
        return False, "hubspot_write_runtime_only"
    return True, "allow"
