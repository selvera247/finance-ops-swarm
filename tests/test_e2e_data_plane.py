from __future__ import annotations

import os

import pytest

os.environ["FINANCE_OPS_DATA_MODE"] = "warehouse"


@pytest.fixture(scope="module")
def e2e_built():
    from data_plane.features.compute import compute_customer_features
    from data_plane.vectors.embed import build_policy_index
    from pipelines.batch.ingest import ingest_batch
    from pipelines.stream.simulator import flush_stream_to_warehouse, seed_demo_stream

    ingest_batch(run_id="test-batch")
    seed_demo_stream()
    flush_stream_to_warehouse()
    compute_customer_features()
    build_policy_index()
    return True


def test_warehouse_aging(e2e_built):
    from finance_ops.tools.invoice_tools import aging_summary

    result = aging_summary("CUST-ACME")
    assert result["invoice_count"] == 2
    assert result["total_open"] == 16700.0


def test_features(e2e_built):
    from finance_ops.tools.feature_tools import lookup_customer_risk

    result = lookup_customer_risk("CUST-NORTH")
    assert result["status"] == "success"
    assert result["features"]["risk_band"] in {"low", "medium", "high"}


def test_vector_rag(e2e_built):
    from finance_ops.tools.rag_tools import search_policies

    result = search_policies("collections escalation")
    assert result["hits"]
