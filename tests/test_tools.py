from __future__ import annotations

from finance_ops.lib.fixtures import reload_fixtures
from finance_ops.tools.contract_tools import lookup_customer_contract
from finance_ops.tools.graph_tools import graph_neighborhood
from finance_ops.tools.invoice_tools import aging_summary, lookup_invoice
from finance_ops.tools.payment_tools import suggest_payment_match
from finance_ops.tools.rag_tools import search_policies


def setup_function() -> None:
    reload_fixtures()


def test_lookup_invoice() -> None:
    result = lookup_invoice("INV-1002")
    assert result["status"] == "success"
    assert result["invoice"]["status"] == "past_due"
    assert "evidence_id" in result["evidence"]


def test_aging_summary_acme() -> None:
    result = aging_summary("CUST-ACME")
    assert result["invoice_count"] == 2
    assert result["total_open"] == 16700.0


def test_suggest_payment_match() -> None:
    result = suggest_payment_match("PAY-9002")
    assert result["needs_review"] is True
    assert result["recommendation"] in {"INV-1001", "INV-1002"}


def test_contract_northwind() -> None:
    result = lookup_customer_contract("CUST-NORTH")
    assert result["contracts"][0]["payment_terms"] == "Net 45"


def test_graph_neighborhood() -> None:
    result = graph_neighborhood("PAY-9002", max_hops=2)
    assert result["nodes_reached"] >= 2


def test_policy_search() -> None:
    # Ensure warehouse+index for RAG path
    from data_plane.vectors.embed import build_policy_index
    from pipelines.batch.ingest import ingest_batch

    ingest_batch(run_id="test-rag-batch")
    build_policy_index()
    result = search_policies("collections escalation past due")
    assert result["hits"]
