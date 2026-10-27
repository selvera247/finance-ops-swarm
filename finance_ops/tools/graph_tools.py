from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from data_plane import repository as repo
from finance_ops.lib.evidence import record_evidence


def graph_status() -> dict[str, Any]:
    """L5 GraphStore backend status."""
    from data_plane.graph.store import get_graph_store

    status = get_graph_store().status()
    return {"status": "success", "graph": status, "needs_review": not status.get("ok", False)}


def _adjacency() -> dict[str, list[tuple[str, str]]]:
    graph = repo.knowledge_graph()
    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in graph["edges"]:
        adj[edge["source"]].append((edge["target"], edge["type"]))
        adj[edge["target"]].append((edge["source"], f"INV:{edge['type']}"))
    return adj


def get_entity(entity_id: str) -> dict[str, Any]:
    entity_id = entity_id.strip().upper()
    graph = repo.knowledge_graph()
    node = next((n for n in graph["nodes"] if n["id"] == entity_id), None)
    if not node:
        result = {"status": "not_found", "entity_id": entity_id, "needs_review": True}
        result["evidence"] = record_evidence(
            agent="reconciliation_agent", action="get_entity",
            inputs={"entity_id": entity_id}, outputs=result, sources=[],
        )
        return result
    edges = [e for e in graph["edges"] if e["source"] == entity_id or e["target"] == entity_id]
    result = {"status": "success", "entity": node, "edges": edges, "needs_review": False}
    result["evidence"] = record_evidence(
        agent="reconciliation_agent", action="get_entity",
        inputs={"entity_id": entity_id}, outputs={"edge_count": len(edges)},
        sources=[repo.source_label() + ":knowledge_graph"],
    )
    return result


def graph_neighborhood(entity_id: str, max_hops: int = 2) -> dict[str, Any]:
    entity_id = entity_id.strip().upper()
    max_hops = max(1, min(int(max_hops), 4))
    graph = repo.knowledge_graph()
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    if entity_id not in nodes_by_id:
        result = {"status": "not_found", "entity_id": entity_id, "needs_review": True}
        result["evidence"] = record_evidence(
            agent="reconciliation_agent", action="graph_neighborhood",
            inputs={"entity_id": entity_id, "max_hops": max_hops}, outputs=result, sources=[],
        )
        return result
    adj = _adjacency()
    visited = {entity_id: 0}
    paths: list[dict[str, Any]] = []
    queue: deque[tuple[str, int, list[str]]] = deque([(entity_id, 0, [entity_id])])
    while queue:
        current, depth, path = queue.popleft()
        if depth >= max_hops:
            continue
        for neighbor, rel in adj.get(current, []):
            if neighbor in visited and visited[neighbor] < depth + 1:
                continue
            visited[neighbor] = depth + 1
            paths.append({
                "node": nodes_by_id.get(neighbor, {"id": neighbor}),
                "depth": depth + 1,
                "path": path + [f"-{rel}->", neighbor],
            })
            queue.append((neighbor, depth + 1, path + [neighbor]))
    result = {
        "status": "success", "entity_id": entity_id, "max_hops": max_hops,
        "nodes_reached": len(visited), "neighborhood": paths[:40], "needs_review": False,
    }
    result["evidence"] = record_evidence(
        agent="reconciliation_agent", action="graph_neighborhood",
        inputs={"entity_id": entity_id, "max_hops": max_hops},
        outputs={"nodes_reached": len(visited)},
        sources=[repo.source_label() + ":knowledge_graph"],
    )
    return result
