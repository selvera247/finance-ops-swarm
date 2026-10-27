from __future__ import annotations

from google.adk.agents.llm_agent import Agent

from finance_ops.governance.callbacks import (
    after_agent_registry,
    before_agent_registry,
    before_tool_rbac,
)
from finance_ops.lib.config import default_model
from finance_ops.specialists import (
    contracts_agent,
    invoice_agent,
    payments_agent,
    reconciliation_agent,
)
from finance_ops.tools.bigquery_tools import bigquery_status
from finance_ops.tools.craft_tools import (
    budget_pack_context,
    heal_tool_result,
    sanitize_payload,
)
from finance_ops.tools.governance_tools import (
    flag_for_human_review,
    get_evidence,
    recent_evidence,
)
from finance_ops.tools.gui_tools import (
    fetch_legacy_bank_statement,
    list_bank_statements,
    list_portal_extracts,
    process_portal_incoming,
)
from finance_ops.tools.memory_tools import (
    memory_evict,
    memory_get,
    memory_list,
    memory_promote,
    memory_put,
    memory_search,
    memory_status,
)
from finance_ops.tools.portal_spike_tools import (
    classify_portal_exception,
    spike_b_walkthrough,
)
from finance_ops.tools.rag_tools import search_policies
from finance_ops.tools.runtime_tools import (
    circuit_status,
    get_approval,
    get_workflow_status,
    list_pending_approvals,
    reset_circuit_breaker,
    resolve_portal_with_fallback,
    resume_durable_workflow,
    run_typed_a2a_aging,
    start_durable_reconcile,
)
from finance_ops.tools.sandbox_tools import (
    run_sandboxed_calc,
    run_sandboxed_python,
    sandbox_status,
)
from finance_ops.tools.shadow_tools import (
    get_shadow_trajectory,
    list_shadow_trajectories,
    shadow_cash_app_trajectory,
    shadow_spike_a_walkthrough,
    shadow_spike_b_walkthrough,
)

root_agent = Agent(
    model=default_model(),
    name="finance_ops_coordinator",
    description=(
        "Finance operations coordinator for AR, cash app, contracts, graph reconciliation, "
        "multi-portal GUI extracts, HITL approvals, durable reconcile, and typed A2A handoffs."
    ),
    instruction=(
        "You are the Finance Ops coordinator.\n"
        "Routing: invoices/aging/risk → invoice_agent; payments → payments_agent; "
        "contracts → contracts_agent; graph entity walks → reconciliation_agent.\n"
        "IMPORTANT — portal / extract / SageSure / payer / bank statement requests:\n"
        "Do NOT transfer to reconciliation_agent. Call resolve_portal_with_fallback "
        "(or list_portal_extracts / process_portal_incoming) yourself.\n"
        "Portal extract flow:\n"
        "- Prefer resolve_portal_with_fallback (warehouse/API first, browser on miss)\n"
        "- fetch_legacy_bank_statement for forced GUI pull\n"
        "- process_portal_incoming to drain data/incoming/<portal_id>/\n"
        "- list_portal_extracts (or list_bank_statements) to inspect ingested rows\n"
        "Spike B (payer_availity): after load_spike_b, use spike_b_walkthrough / "
        "classify_portal_exception; transfer portal HITL review to payments_agent; "
        "shadow_spike_b_walkthrough for dry demos.\n"
        "HITL: you may list/get approvals (read-only). "
        "Payment/approval mutations (request_approval, decide_approval, "
        "request_cash_app_approval, apply_payment_match) → payments_agent only.\n"
        "Durable: start_durable_reconcile / resume_durable_workflow for multi-step DAG.\n"
        "Typed A2A: run_typed_a2a_aging for structured invoice specialist handoffs.\n"
        "Circuit: circuit_status if tools fail with circuit_open.\n"
        "Sandbox: run_sandboxed_calc / run_sandboxed_python for formulas only; "
        "they cannot apply matches or call write tools — use HITL for mutations. "
        "sandbox_status reports C7-C Docker isolation readiness.\n"
        "Shadow (C3): shadow_cash_app_trajectory / shadow_spike_a_walkthrough / "
        "shadow_spike_b_walkthrough propose HITL without mutating; "
        "list/get_shadow_trajectory to inspect.\n"
        "Memory (C2): working / episodic / long_term via memory_put/get/search/list; "
        "memory_promote upward; memory_evict / memory_status for caps. "
        "Use working for session scratch, episodic for turn notes, long_term for durable facts.\n"
        "Craft C4–C6: budget_pack_context before stuffing large tool JSON into reasoning; "
        "sanitize_payload to preview redaction; heal_tool_result on failures "
        "(retry once, then needs_review — never invent balances).\n"
        "RBAC is code-enforced: denied tools return status=denied.\n"
        "Always cite evidence_id. For write-offs say needs_review.\n"
        "Never invent balances."
    ),
    tools=[
        search_policies,
        flag_for_human_review,
        get_evidence,
        recent_evidence,
        bigquery_status,
        fetch_legacy_bank_statement,
        process_portal_incoming,
        list_portal_extracts,
        list_bank_statements,
        classify_portal_exception,
        spike_b_walkthrough,
        resolve_portal_with_fallback,
        list_pending_approvals,
        get_approval,
        start_durable_reconcile,
        resume_durable_workflow,
        get_workflow_status,
        run_typed_a2a_aging,
        circuit_status,
        reset_circuit_breaker,
        run_sandboxed_calc,
        run_sandboxed_python,
        sandbox_status,
        shadow_cash_app_trajectory,
        shadow_spike_a_walkthrough,
        shadow_spike_b_walkthrough,
        list_shadow_trajectories,
        get_shadow_trajectory,
        memory_put,
        memory_get,
        memory_search,
        memory_list,
        memory_promote,
        memory_evict,
        memory_status,
        budget_pack_context,
        sanitize_payload,
        heal_tool_result,
    ],
    sub_agents=[invoice_agent, payments_agent, contracts_agent, reconciliation_agent],
    before_tool_callback=before_tool_rbac,
    before_agent_callback=before_agent_registry,
    after_agent_callback=after_agent_registry,
)
