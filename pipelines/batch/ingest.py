from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from data_plane.config import DATA_DIR
from data_plane.warehouse import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def ingest_batch(run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or f"batch-{uuid.uuid4().hex[:10]}"
    started = _now()
    db.init_schema()
    con = db.connect()
    try:
        now = _now()
        invoices = _load_json("invoices.json")
        payments = _load_json("payments.json")
        contracts = _load_json("contracts.json")
        graph = _load_json("knowledge_graph.json")
        corpus = _load_json("rag_corpus.json")

        for table in ("invoices", "payments", "contracts", "kg_nodes", "kg_edges", "policy_docs"):
            con.execute(f"DELETE FROM {table}")

        for row in invoices:
            con.execute(
                "INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [row["invoice_id"], row["customer_id"], row["customer_name"], row["contract_id"],
                 row["amount"], row["currency"], row["issue_date"], row["due_date"],
                 row["status"], row["aging_bucket"], row["po_number"], now],
            )
        for row in payments:
            con.execute(
                "INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?,?)",
                [row["payment_id"], row["customer_id"], row["amount"], row["currency"],
                 row["payment_date"], row["method"], row["reference"],
                 row.get("matched_invoice_id"), row["status"], now],
            )
        for row in contracts:
            con.execute(
                "INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [row["contract_id"], row["customer_id"], row["customer_name"],
                 row["effective_date"], row["end_date"], row["payment_terms"],
                 row["currency"], row["credit_limit"], row["sla_notes"], row["status"], now],
            )
        for node in graph["nodes"]:
            con.execute("INSERT INTO kg_nodes VALUES (?,?,?)", [node["id"], node["type"], node["label"]])
        for edge in graph["edges"]:
            con.execute("INSERT INTO kg_edges VALUES (?,?,?)", [edge["source"], edge["target"], edge["type"]])
        for doc in corpus:
            con.execute("INSERT INTO policy_docs VALUES (?,?,?,?)", [doc["doc_id"], doc["title"], doc["text"], now])

        counts = {
            "invoices": len(invoices), "payments": len(payments), "contracts": len(contracts),
            "kg_nodes": len(graph["nodes"]), "kg_edges": len(graph["edges"]), "policy_docs": len(corpus),
        }
        finished = _now()
        con.execute(
            "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?,?,?)",
            [run_id, "batch_ingest", "success", json.dumps(counts), started, finished],
        )
        return {"run_id": run_id, "status": "success", "counts": counts}
    finally:
        con.close()
