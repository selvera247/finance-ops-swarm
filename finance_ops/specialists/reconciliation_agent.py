from __future__ import annotations

from google.adk.agents.llm_agent import Agent

from finance_ops.governance.callbacks import (
    after_agent_registry,
    before_agent_registry,
    before_tool_rbac,
)
from finance_ops.lib.config import default_model
from finance_ops.tools.graph_tools import get_entity, graph_neighborhood, graph_status
from finance_ops.tools.hubspot_tools import (
    get_company,
    get_deal,
    get_deal_line_items,
    get_open_tickets_for_company,
    list_closed_won_deals,
    match_hubspot_company,
)
from finance_ops.tools.payment_tools import suggest_payment_match
from finance_ops.tools.rag_tools import search_policies

reconciliation_agent = Agent(
    model=default_model(),
    name="reconciliation_agent",
    description="Specialist for knowledge-graph reconciliation and GraphRAG walks.",
    instruction=(
        "Explain entity hop paths. Cite ids and evidence_id. Flag ambiguity for review. "
        "Use match_hubspot_company for domain/name/external-id candidates; "
        "duplicates → needs_review; never auto-merge CRM records."
    ),
    tools=[
        get_entity,
        graph_neighborhood,
        graph_status,
        search_policies,
        suggest_payment_match,
        get_company,
        get_deal,
        list_closed_won_deals,
        get_deal_line_items,
        get_open_tickets_for_company,
        match_hubspot_company,
    ],
    before_tool_callback=before_tool_rbac,
    before_agent_callback=before_agent_registry,
    after_agent_callback=after_agent_registry,
)
