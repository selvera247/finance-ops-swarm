"""Sync knowledge graph from fixtures/warehouse into the configured GraphStore."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_plane.config import DATA_DIR
from data_plane.graph.store import get_graph_store


def load_source_graph() -> dict[str, Any]:
    """Prefer warehouse kg_* tables; else data/knowledge_graph.json."""
    try:
        from data_plane.config import DUCKDB_PATH
        from data_plane.warehouse import db

        if DUCKDB_PATH.exists():
            db.init_schema()
            nodes = db.query_dicts("SELECT id, type, label FROM kg_nodes")
            edges = db.query_dicts("SELECT source, target, type FROM kg_edges")
            if nodes:
                return {"nodes": nodes, "edges": edges, "source": "warehouse"}
    except Exception:
        pass

    path = DATA_DIR / "knowledge_graph.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["source"] = "fixture_json"
    return data


def sync_knowledge_graph() -> dict[str, Any]:
    src = load_source_graph()
    store = get_graph_store()
    result = store.replace_all(src.get("nodes") or [], src.get("edges") or [])
    result["source"] = src.get("source")
    result["store_status"] = store.status()
    return result
