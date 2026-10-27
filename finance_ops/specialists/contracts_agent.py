from __future__ import annotations

from google.adk.agents.llm_agent import Agent

from finance_ops.governance.callbacks import (
    after_agent_registry,
    before_agent_registry,
    before_tool_rbac,
)
from finance_ops.lib.config import default_model
from finance_ops.tools.contract_tools import lookup_contract, lookup_customer_contract
from finance_ops.tools.hubspot_tools import (
    compare_sold_contracted_invoiced,
    get_company,
    get_deal,
    get_deal_line_items,
    get_open_tickets_for_company,
    list_closed_won_deals,
)

contracts_agent = Agent(
    model=default_model(),
    name="contracts_agent",
    description="Specialist for contract terms, credit limits, and SLA notes.",
    instruction=(
        "Contracts specialist. Quote payment_terms and cite contract_id + evidence_id. "
        "Use compare_sold_contracted_invoiced for sold vs contracted vs invoiced with "
        "EvidenceRef sources; flag gaps for review."
    ),
    tools=[
        lookup_contract,
        lookup_customer_contract,
        get_company,
        get_deal,
        list_closed_won_deals,
        get_deal_line_items,
        get_open_tickets_for_company,
        compare_sold_contracted_invoiced,
    ],
    before_tool_callback=before_tool_rbac,
    before_agent_callback=before_agent_registry,
    after_agent_callback=after_agent_registry,
)
