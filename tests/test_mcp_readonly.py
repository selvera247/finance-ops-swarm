"""Read-only MCP server registers expected tools and serves aging."""

from __future__ import annotations

import asyncio
import json

import pytest

from finance_ops.mcp.server import build_server
from pipelines.batch.ingest import ingest_batch
from scripts.load_spike_a import load as load_spike_a

# Write tools must never appear on the MCP surface
FORBIDDEN = {
    "apply_payment_match",
    "request_cash_app_approval",
    "request_approval",
    "decide_approval",
    "fetch_legacy_bank_statement",
    "process_portal_incoming",
    "start_durable_reconcile",
}

EXPECTED = {
    "aging_summary",
    "list_open_invoices",
    "lookup_invoice",
    "list_unmatched_payments",
    "lookup_payment",
    "suggest_payment_match",
    "search_policies",
    "get_evidence",
    "recent_evidence",
    "bigquery_status",
    "graph_neighborhood",
}


@pytest.fixture(scope="module")
def server():
    ingest_batch(run_id="mcp-test-batch")
    load_spike_a(replace_customers=True)
    return build_server()


def test_tool_catalog(server) -> None:
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED <= names
    assert not (names & FORBIDDEN)


def test_aging_via_mcp(server) -> None:
    result = asyncio.run(
        server.call_tool("aging_summary", {"customer_id": "CUST-ACME"})
    )
    assert result.is_error is False
    text = result.content[0].text
    data = json.loads(text)
    assert data["status"] == "success"
    assert data["total_open"] == 16700.0


def test_suggest_match_via_mcp_no_apply(server) -> None:
    result = asyncio.run(
        server.call_tool("suggest_payment_match", {"payment_id": "PAY-2001"})
    )
    assert result.is_error is False
    data = json.loads(result.content[0].text)
    assert data["status"] == "success"
    assert data["needs_review"] is True
    assert data["candidates"]
