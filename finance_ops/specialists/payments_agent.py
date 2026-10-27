from __future__ import annotations

from google.adk.agents.llm_agent import Agent

from finance_ops.governance.callbacks import (
    after_agent_registry,
    before_agent_registry,
    before_tool_rbac,
)
from finance_ops.lib.config import default_model
from finance_ops.tools.payment_tools import (
    apply_payment_match,
    list_unmatched_payments,
    lookup_payment,
    request_cash_app_approval,
    suggest_payment_match,
)
from finance_ops.tools.craft_tools import (
    budget_pack_context,
    heal_suggest_payment,
    heal_tool_result,
)
from finance_ops.tools.memory_tools import (
    memory_get,
    memory_promote,
    memory_put,
    memory_search,
)
from finance_ops.tools.runtime_tools import (
    decide_approval,
    get_approval,
    list_pending_approvals,
    request_approval,
)
from finance_ops.tools.sandbox_tools import run_sandboxed_calc, run_sandboxed_python
from finance_ops.tools.shadow_tools import (
    get_shadow_trajectory,
    list_shadow_trajectories,
    shadow_cash_app_trajectory,
    shadow_spike_a_walkthrough,
)

payments_agent = Agent(
    model=default_model(),
    name="payments_agent",
    description="Specialist for payments, unmatched cash, match suggestions, and HITL apply.",
    instruction=(
        "Payments specialist. Treat matches as needs_review unless already matched. "
        "For cash app: suggest_payment_match then request_cash_app_approval "
        "(Slack/HITL); do not call apply_payment_match unless ops explicitly bypasses HITL. "
        "HITL: request_approval / decide_approval / get_approval / list_pending_approvals "
        "live here (coordinator is read-only for approvals). "
        "On suggest failures use heal_suggest_payment (one retry then needs_review). "
        "After list_unmatched_payments, budget_pack_context to keep context small. "
        "Shadow (C3): shadow_cash_app_trajectory or shadow_spike_a_walkthrough to record "
        "what would happen without HITL/apply/Slack — prefer for dry demos. "
        "Memory (C2): memory_put working notes per payment; promote to episodic/long_term "
        "when a match pattern is durable; memory_get/search before re-suggesting. "
        "For amount tolerances / remittance math use run_sandboxed_calc or run_sandboxed_python "
        "(returns numbers only — never applies matches). "
        "Cite payment_id and evidence_id."
    ),
    tools=[
        lookup_payment,
        list_unmatched_payments,
        suggest_payment_match,
        request_cash_app_approval,
        apply_payment_match,
        request_approval,
        decide_approval,
        get_approval,
        list_pending_approvals,
        run_sandboxed_calc,
        run_sandboxed_python,
        shadow_cash_app_trajectory,
        shadow_spike_a_walkthrough,
        list_shadow_trajectories,
        get_shadow_trajectory,
        memory_put,
        memory_get,
        memory_search,
        memory_promote,
        budget_pack_context,
        heal_suggest_payment,
        heal_tool_result,
    ],
    before_tool_callback=before_tool_rbac,
    before_agent_callback=before_agent_registry,
    after_agent_callback=after_agent_registry,
)
