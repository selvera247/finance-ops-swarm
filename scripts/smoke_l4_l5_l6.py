#!/usr/bin/env python3
"""Smoke L4 vectors, L5 sqlite graph, L6 FastAPI app — no GCP required."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    report: dict = {"checks": {}}

    from data_plane.vectors.embed import build_policy_index, search
    from pipelines.batch.ingest import ingest_batch

    ingest_batch(run_id="smoke-l456-batch")
    built = build_policy_index()
    hits = search("collections escalation", top_k=2)
    report["checks"]["l4_vectors"] = {
        "ok": built.get("count", 0) >= 1 and bool(hits),
        "backend": built.get("backend"),
        "hits": len(hits),
    }

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["FINANCE_OPS_GRAPH_BACKEND"] = "sqlite"
        os.environ["FINANCE_OPS_GRAPH_SQLITE"] = str(Path(tmp) / "kg.sqlite")
        # reset singleton
        import data_plane.graph.store as gs

        gs._STORE = None
        from data_plane.graph.sync import sync_knowledge_graph

        synced = sync_knowledge_graph()
        report["checks"]["l5_graph"] = {
            "ok": synced.get("status") == "success" and synced.get("nodes", 0) >= 3,
            "nodes": synced.get("nodes"),
            "backend": synced.get("backend"),
        }

    from fastapi.testclient import TestClient
    from finance_ops.serving import app

    client = TestClient(app)
    health = client.get("/health").json()
    aging = client.post("/v1/aging", json={"customer_id": "CUST-ACME"}).json()
    report["checks"]["l6_serving"] = {
        "ok": health.get("status") == "ok" and aging.get("invoice_count") == 2,
        "health": health.get("status"),
        "aging_total": aging.get("total_open"),
    }

    ok = all(c.get("ok") for c in report["checks"].values())
    report["status"] = "PASS" if ok else "FAIL"
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
