from __future__ import annotations

from pathlib import Path

from data_plane.graph.store import GraphStore
from data_plane.graph.sync import sync_knowledge_graph
from finance_ops.tools.graph_tools import get_entity, graph_neighborhood, graph_status
from pipelines.batch.ingest import ingest_batch


def setup_function() -> None:
    ingest_batch(run_id="l5-graph-batch")


def test_sqlite_graph_persist(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "kg.sqlite"
    monkeypatch.setenv("FINANCE_OPS_GRAPH_BACKEND", "sqlite")
    monkeypatch.setenv("FINANCE_OPS_GRAPH_SQLITE", str(db_path))
    result = sync_knowledge_graph()
    assert result["status"] == "success"
    assert result["nodes"] >= 3
    assert db_path.exists()

    store = GraphStore(backend="sqlite")
    data = store.load()
    assert any(n["id"] == "CUST-ACME" for n in data["nodes"])
    assert data["backend"] == "sqlite"

    status = graph_status()
    assert status["graph"]["backend"] == "sqlite"
    assert status["graph"]["ok"] is True


def test_graph_tools_after_sqlite_sync(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_GRAPH_BACKEND", "sqlite")
    monkeypatch.setenv("FINANCE_OPS_GRAPH_SQLITE", str(tmp_path / "kg2.sqlite"))
    sync_knowledge_graph()
    entity = get_entity("CUST-ACME")
    assert entity["status"] == "success"
    neigh = graph_neighborhood("PAY-9002", max_hops=2)
    assert neigh["nodes_reached"] >= 2


def test_spanner_backend_selected_from_env(monkeypatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_GRAPH_BACKEND", "spanner")
    monkeypatch.setenv("SPANNER_INSTANCE", "finance-ops")
    monkeypatch.setenv("SPANNER_DATABASE", "finance_ops")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    store = GraphStore()
    assert store.backend == "spanner"
    status = store.status()
    assert status["backend"] == "spanner"
    assert status["configured"] is True
    # No live Spanner in unit tests — load should surface an error, not crash selection
    assert "ok" in status
