"""L5 Knowledge graph backends: duckdb | sqlite | neo4j | spanner.

- duckdb/sqlite: local Graph-shaped edge tables (live default on Cloud Run).
- neo4j: managed Cypher (Aura) when NEO4J_URI / FINANCE_OPS_GRAPH_BACKEND=neo4j.
- spanner: Cloud Spanner Graph-shaped tables (see spanner_schema.sql).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Literal

from data_plane.config import WAREHOUSE_DIR, ensure_dirs


Backend = Literal["duckdb", "sqlite", "neo4j", "spanner"]


def graph_backend() -> Backend:
    raw = os.getenv("FINANCE_OPS_GRAPH_BACKEND", "duckdb").strip().lower()
    if raw in {"duckdb", "sqlite", "neo4j", "spanner"}:
        return raw  # type: ignore[return-value]
    if os.getenv("NEO4J_URI"):
        return "neo4j"
    if os.getenv("SPANNER_INSTANCE") and os.getenv("SPANNER_DATABASE"):
        return "spanner"
    return "duckdb"


def sqlite_graph_path() -> Path:
    ensure_dirs()
    return Path(os.getenv("FINANCE_OPS_GRAPH_SQLITE", str(WAREHOUSE_DIR / "knowledge_graph.sqlite")))


class GraphStore:
    def __init__(self, backend: Backend | None = None) -> None:
        self.backend: Backend = backend or graph_backend()

    def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {"backend": self.backend}
        if self.backend == "sqlite":
            path = sqlite_graph_path()
            info["path"] = str(path)
            info["exists"] = path.exists()
        elif self.backend == "neo4j":
            info["uri"] = os.getenv("NEO4J_URI")
            info["user"] = os.getenv("NEO4J_USER", "neo4j")
            info["configured"] = bool(os.getenv("NEO4J_URI"))
        elif self.backend == "spanner":
            info["instance"] = os.getenv("SPANNER_INSTANCE")
            info["database"] = os.getenv("SPANNER_DATABASE")
            info["configured"] = bool(
                os.getenv("SPANNER_INSTANCE") and os.getenv("SPANNER_DATABASE")
            )
        else:
            from data_plane.config import DUCKDB_PATH

            info["path"] = str(DUCKDB_PATH)
            info["exists"] = DUCKDB_PATH.exists()
        try:
            g = self.load()
            info["nodes"] = len(g.get("nodes") or [])
            info["edges"] = len(g.get("edges") or [])
            info["ok"] = True
        except Exception as exc:  # noqa: BLE001
            info["ok"] = False
            info["error"] = str(exc)
        return info

    def _init_sqlite(self) -> sqlite3.Connection:
        path = sqlite_graph_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS kg_nodes (id TEXT PRIMARY KEY, type TEXT, label TEXT)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS kg_edges (source TEXT, target TEXT, type TEXT)"
        )
        con.commit()
        return con

    def replace_all(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        if self.backend == "neo4j":
            return self._neo4j_replace(nodes, edges)
        if self.backend == "spanner":
            return self._spanner_replace(nodes, edges)
        if self.backend == "sqlite":
            con = self._init_sqlite()
            try:
                con.execute("DELETE FROM kg_edges")
                con.execute("DELETE FROM kg_nodes")
                con.executemany(
                    "INSERT INTO kg_nodes(id, type, label) VALUES (?,?,?)",
                    [(n["id"], n.get("type"), n.get("label")) for n in nodes],
                )
                con.executemany(
                    "INSERT INTO kg_edges(source, target, type) VALUES (?,?,?)",
                    [(e["source"], e["target"], e.get("type")) for e in edges],
                )
                con.commit()
            finally:
                con.close()
            return {"status": "success", "backend": "sqlite", "nodes": len(nodes), "edges": len(edges)}

        # duckdb — write through warehouse tables
        from data_plane.warehouse import db

        db.init_schema()
        con = db.connect()
        try:
            con.execute("DELETE FROM kg_edges")
            con.execute("DELETE FROM kg_nodes")
            for n in nodes:
                con.execute(
                    "INSERT OR REPLACE INTO kg_nodes VALUES (?,?,?)",
                    [n["id"], n.get("type"), n.get("label")],
                )
            for e in edges:
                con.execute(
                    "INSERT INTO kg_edges VALUES (?,?,?)",
                    [e["source"], e["target"], e.get("type")],
                )
        finally:
            con.close()
        return {"status": "success", "backend": "duckdb", "nodes": len(nodes), "edges": len(edges)}

    def load(self) -> dict[str, Any]:
        if self.backend == "neo4j":
            return self._neo4j_load()
        if self.backend == "spanner":
            return self._spanner_load()
        if self.backend == "sqlite":
            con = self._init_sqlite()
            try:
                nodes = [
                    {"id": r[0], "type": r[1], "label": r[2]}
                    for r in con.execute("SELECT id, type, label FROM kg_nodes").fetchall()
                ]
                edges = [
                    {"source": r[0], "target": r[1], "type": r[2]}
                    for r in con.execute("SELECT source, target, type FROM kg_edges").fetchall()
                ]
                return {"nodes": nodes, "edges": edges, "backend": "sqlite"}
            finally:
                con.close()

        from data_plane.warehouse import db

        db.init_schema()
        return {
            "nodes": db.query_dicts("SELECT id, type, label FROM kg_nodes"),
            "edges": db.query_dicts("SELECT source, target, type FROM kg_edges"),
            "backend": "duckdb",
        }

    def cypher_neighborhood(self, entity_id: str, max_hops: int = 2) -> list[dict[str, Any]]:
        """Neo4j Cypher neighborhood; other backends raise to use in-memory walk."""
        if self.backend != "neo4j":
            raise RuntimeError("cypher_neighborhood requires neo4j backend")
        driver = self._neo4j_driver()
        q = """
        MATCH p=(n {id: $id})-[*1..$hops]-(m)
        RETURN m.id AS id, m.type AS type, m.label AS label, length(p) AS depth
        LIMIT 40
        """
        # Neo4j params can't bind hop in all versions — interpolate safely as int
        hops = max(1, min(int(max_hops), 4))
        q = f"""
        MATCH p=(n {{id: $id}})-[*1..{hops}]-(m)
        RETURN DISTINCT m.id AS id, m.type AS type, m.label AS label, length(p) AS depth
        LIMIT 40
        """
        with driver.session() as session:
            rows = session.run(q, id=entity_id)
            return [dict(r) for r in rows]

    def _neo4j_driver(self):
        uri = os.getenv("NEO4J_URI")
        if not uri:
            raise RuntimeError("NEO4J_URI not set")
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("neo4j driver not installed") from exc
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "financeops")
        return GraphDatabase.driver(uri, auth=(user, password))

    def _spanner_db(self):
        try:
            from google.cloud import spanner
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("google-cloud-spanner not installed") from exc
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        instance_id = os.getenv("SPANNER_INSTANCE")
        database_id = os.getenv("SPANNER_DATABASE")
        if not project or not instance_id or not database_id:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT, SPANNER_INSTANCE, SPANNER_DATABASE required")
        client = spanner.Client(project=project)
        return client.instance(instance_id).database(database_id)

    def _spanner_replace(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        import uuid

        from google.cloud.spanner_v1 import param_types

        db = self._spanner_db()

        def _txn(transaction):
            transaction.execute_update("DELETE FROM kg_edges WHERE true")
            transaction.execute_update("DELETE FROM kg_nodes WHERE true")
            for n in nodes:
                transaction.execute_update(
                    "INSERT INTO kg_nodes (id, type, label) VALUES (@id, @type, @label)",
                    params={"id": n["id"], "type": n.get("type"), "label": n.get("label")},
                    param_types={
                        "id": param_types.STRING,
                        "type": param_types.STRING,
                        "label": param_types.STRING,
                    },
                )

            for e in edges:
                eid = e.get("edge_id") or uuid.uuid4().hex[:16]
                transaction.execute_update(
                    "INSERT INTO kg_edges (source, target, type, edge_id) "
                    "VALUES (@source, @target, @type, @edge_id)",
                    params={
                        "source": e["source"],
                        "target": e["target"],
                        "type": e.get("type"),
                        "edge_id": eid,
                    },
                    param_types={
                        "source": param_types.STRING,
                        "target": param_types.STRING,
                        "type": param_types.STRING,
                        "edge_id": param_types.STRING,
                    },
                )

        db.run_in_transaction(_txn)
        return {
            "status": "success",
            "backend": "spanner",
            "nodes": len(nodes),
            "edges": len(edges),
        }

    def _spanner_load(self) -> dict[str, Any]:
        db = self._spanner_db()
        # multi_use: two queries share one snapshot (single-use snaps raise ValueError)
        with db.snapshot(multi_use=True) as snapshot:
            nodes = [
                {"id": r[0], "type": r[1], "label": r[2]}
                for r in snapshot.execute_sql("SELECT id, type, label FROM kg_nodes")
            ]
            edges = [
                {"source": r[0], "target": r[1], "type": r[2]}
                for r in snapshot.execute_sql("SELECT source, target, type FROM kg_edges")
            ]
        return {"nodes": nodes, "edges": edges, "backend": "spanner"}

    def _neo4j_replace(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        driver = self._neo4j_driver()
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            for n in nodes:
                session.run(
                    "CREATE (n:Entity {id: $id, type: $type, label: $label})",
                    id=n["id"],
                    type=n.get("type"),
                    label=n.get("label"),
                )
            for e in edges:
                session.run(
                    """
                    MATCH (a:Entity {id: $source}), (b:Entity {id: $target})
                    CREATE (a)-[r:REL {type: $type}]->(b)
                    """,
                    source=e["source"],
                    target=e["target"],
                    type=e.get("type"),
                )
        driver.close()
        return {"status": "success", "backend": "neo4j", "nodes": len(nodes), "edges": len(edges)}

    def _neo4j_load(self) -> dict[str, Any]:
        driver = self._neo4j_driver()
        with driver.session() as session:
            nodes = [
                {"id": r["id"], "type": r["type"], "label": r["label"]}
                for r in session.run("MATCH (n:Entity) RETURN n.id AS id, n.type AS type, n.label AS label")
            ]
            edges = [
                {"source": r["source"], "target": r["target"], "type": r["type"]}
                for r in session.run(
                    "MATCH (a:Entity)-[r:REL]->(b:Entity) "
                    "RETURN a.id AS source, b.id AS target, r.type AS type"
                )
            ]
        driver.close()
        return {"nodes": nodes, "edges": edges, "backend": "neo4j"}


_STORE: GraphStore | None = None


def get_graph_store() -> GraphStore:
    global _STORE
    if _STORE is None or _STORE.backend != graph_backend():
        _STORE = GraphStore()
    return _STORE


def export_graph_json(path: Path | None = None) -> Path:
    ensure_dirs()
    path = path or (WAREHOUSE_DIR / "knowledge_graph_export.json")
    data = get_graph_store().load()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
