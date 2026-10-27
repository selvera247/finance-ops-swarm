from __future__ import annotations

from typing import Any

from data_plane.config import bigquery_dataset, data_mode, gcp_project
from data_plane.vectors.embed import vertex_vector_status
from data_plane.warehouse import db
from data_plane.warehouse.bq_adapter import bq_ping


def bigquery_status() -> dict[str, Any]:
    mode = data_mode()
    project = gcp_project()
    duck_ready = False
    counts: dict[str, Any] = {}
    try:
        from data_plane.config import DUCKDB_PATH

        duck_ready = DUCKDB_PATH.exists()
        if duck_ready:
            counts = {
                "invoices": db.query_dicts("SELECT COUNT(*) AS n FROM invoices")[0]["n"],
                "payments": db.query_dicts("SELECT COUNT(*) AS n FROM payments")[0]["n"],
                "features": db.query_dicts("SELECT COUNT(*) AS n FROM customer_features")[0]["n"],
                "stream_events": db.query_dicts("SELECT COUNT(*) AS n FROM stream_events")[0]["n"],
                "bank_statements": db.query_dicts("SELECT COUNT(*) AS n FROM bank_statements")[0]["n"],
                "portal_extracts": db.query_dicts("SELECT COUNT(*) AS n FROM portal_extracts")[0][
                    "n"
                ],
            }
    except Exception as exc:  # noqa: BLE001
        counts = {"error": str(exc)}

    bq = bq_ping()
    return {
        "status": "success",
        "data_mode": mode,
        "project": project,
        "dataset": bigquery_dataset(),
        "bigquery": bq,
        "active_source": (
            "bigquery"
            if mode == "bigquery" and bq.get("ok")
            else ("duckdb_fallback" if mode == "bigquery" else mode)
        ),
        "duckdb_ready": duck_ready,
        "warehouse_counts": counts,
        "vertex_vectors": vertex_vector_status(),
        "gui_connector": "gui_connectors/ (Playwright + mock portal)",
        "needs_review": mode == "bigquery" and not bq.get("ok"),
        "hint": (
            None
            if mode != "bigquery" or bq.get("ok")
            else "Set GOOGLE_CLOUD_PROJECT + ADC; invoice/payment tools fall back to DuckDB"
        ),
    }
