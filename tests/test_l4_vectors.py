from __future__ import annotations

from data_plane.vectors import embed
from data_plane.vectors import vertex_embed as vx
from finance_ops.tools.rag_tools import search_policies
from pipelines.batch.ingest import ingest_batch


def setup_function() -> None:
    ingest_batch(run_id="l4-vector-batch")


def test_build_and_search_local_me_sim(monkeypatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_USE_VERTEX_VECTORS", "false")
    built = embed.build_policy_index()
    assert built["status"] == "success"
    assert built["count"] >= 1
    assert built["backend"] == "local_hash"
    hits = embed.search("collections escalation past due", top_k=3)
    assert hits
    assert "doc_id" in hits[0]
    assert hits[0].get("backend")


def test_search_policies_tool() -> None:
    embed.build_policy_index()
    result = search_policies("write off unmatched payment")
    assert result["status"] == "success"
    assert result["hits"]
    assert "evidence" in result


def test_vertex_status_default() -> None:
    status = vx.vertex_status()
    assert status["enabled"] is False
    assert status["active_backend"] == "local_hash"
