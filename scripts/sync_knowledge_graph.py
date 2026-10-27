#!/usr/bin/env python3
"""L5: sync KG into FINANCE_OPS_GRAPH_BACKEND (duckdb|sqlite|neo4j|spanner)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=["duckdb", "sqlite", "neo4j", "spanner"],
        default=None,
        help="Override FINANCE_OPS_GRAPH_BACKEND for this run",
    )
    parser.add_argument("--export", action="store_true", help="Also write JSON export")
    args = parser.parse_args()

    if args.backend:
        import os

        os.environ["FINANCE_OPS_GRAPH_BACKEND"] = args.backend

    from data_plane.graph.store import export_graph_json
    from data_plane.graph.sync import sync_knowledge_graph
    from pipelines.batch.ingest import ingest_batch

    ingest_batch(run_id="pre-graph-sync")
    result = sync_knowledge_graph()
    if args.export:
        path = export_graph_json()
        result["export"] = str(path)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
