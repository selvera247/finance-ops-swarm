from __future__ import annotations

from typing import Any

from data_plane.config import data_mode
from finance_ops.lib import fixtures


def _warehouse_ready() -> bool:
    from data_plane.config import DUCKDB_PATH

    return DUCKDB_PATH.exists()


def list_invoices(*, customer_id: str | None = None, open_only: bool = False) -> list[dict[str, Any]]:
    mode = data_mode()
    if mode == "fixtures" or (mode == "warehouse" and not _warehouse_ready()):
        rows = fixtures.invoices()
        if customer_id:
            rows = [r for r in rows if r["customer_id"] == customer_id]
        if open_only:
            rows = [r for r in rows if r["status"] in {"open", "past_due"}]
        return rows
    if mode == "bigquery":
        from data_plane.warehouse.bq_adapter import bq_list_invoices

        return bq_list_invoices(customer_id=customer_id, open_only=open_only)
    from data_plane.warehouse import db

    sql, params = "SELECT * FROM invoices WHERE 1=1", []
    if customer_id:
        sql += " AND customer_id = ?"
        params.append(customer_id)
    if open_only:
        sql += " AND status IN ('open', 'past_due')"
    return db.query_dicts(sql, params)


def get_invoice(invoice_id: str) -> dict[str, Any] | None:
    rows = [r for r in list_invoices() if str(r.get("invoice_id", "")).upper() == invoice_id.upper()]
    return rows[0] if rows else None


def list_payments(*, customer_id: str | None = None, unmatched_only: bool = False) -> list[dict[str, Any]]:
    mode = data_mode()
    if mode == "fixtures" or (mode == "warehouse" and not _warehouse_ready()):
        rows = fixtures.payments()
        if customer_id:
            rows = [r for r in rows if r["customer_id"] == customer_id]
        if unmatched_only:
            rows = [r for r in rows if r["status"] in {"unmatched", "partial"}]
        return rows
    if mode == "bigquery":
        from data_plane.warehouse.bq_adapter import bq_list_payments

        return bq_list_payments(customer_id=customer_id, unmatched_only=unmatched_only)
    from data_plane.warehouse import db

    sql, params = "SELECT * FROM payments WHERE 1=1", []
    if customer_id:
        sql += " AND customer_id = ?"
        params.append(customer_id)
    if unmatched_only:
        sql += " AND status IN ('unmatched', 'partial')"
    return db.query_dicts(sql, params)


def get_payment(payment_id: str) -> dict[str, Any] | None:
    rows = [r for r in list_payments() if str(r.get("payment_id", "")).upper() == payment_id.upper()]
    return rows[0] if rows else None


def apply_payment_match(payment_id: str, invoice_id: str) -> dict[str, Any]:
    """Mark payment matched to invoice (warehouse and/or BigQuery)."""
    payment_id = payment_id.strip().upper()
    invoice_id = invoice_id.strip().upper()
    payment = get_payment(payment_id)
    if not payment:
        return {"ok": False, "error": "payment_not_found", "payment_id": payment_id}
    invoice = get_invoice(invoice_id)
    if not invoice:
        return {"ok": False, "error": "invoice_not_found", "invoice_id": invoice_id}
    if str(payment.get("customer_id")) != str(invoice.get("customer_id")):
        return {
            "ok": False,
            "error": "customer_mismatch",
            "payment_customer": payment.get("customer_id"),
            "invoice_customer": invoice.get("customer_id"),
        }

    mode = data_mode()
    backends: list[str] = []

    # Always persist to DuckDB when warehouse file exists (local + BQ dual-write for demos)
    if _warehouse_ready() or mode == "warehouse":
        from data_plane.warehouse import db

        db.init_schema()
        db.execute(
            "UPDATE payments SET matched_invoice_id = ?, status = ? WHERE payment_id = ?",
            [invoice_id, "matched", payment_id],
        )
        backends.append("duckdb")

    if mode == "bigquery":
        from data_plane.warehouse.bq_adapter import bq_apply_payment_match

        bq_result = bq_apply_payment_match(payment_id, invoice_id)
        if bq_result.get("ok"):
            backends.append("bigquery")
        else:
            return {
                "ok": False,
                "error": bq_result.get("error", "bq_apply_failed"),
                "backends": backends,
                "bq": bq_result,
            }

    if not backends:
        return {"ok": False, "error": "no_writable_backend", "mode": mode}

    return {
        "ok": True,
        "payment_id": payment_id,
        "invoice_id": invoice_id,
        "status": "matched",
        "backends": backends,
    }


def list_contracts(*, customer_id: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    mode = data_mode()
    if mode == "fixtures" or (mode == "warehouse" and not _warehouse_ready()):
        rows = fixtures.contracts()
        if customer_id:
            rows = [r for r in rows if r["customer_id"] == customer_id]
        if active_only:
            rows = [r for r in rows if r["status"] == "active"]
        return rows
    if mode == "bigquery":
        from data_plane.warehouse.bq_adapter import bq_list_contracts

        return bq_list_contracts(customer_id=customer_id, active_only=active_only)
    from data_plane.warehouse import db

    sql, params = "SELECT * FROM contracts WHERE 1=1", []
    if customer_id:
        sql += " AND customer_id = ?"
        params.append(customer_id)
    if active_only:
        sql += " AND status = 'active'"
    return db.query_dicts(sql, params)


def get_contract(contract_id: str) -> dict[str, Any] | None:
    rows = [
        r
        for r in list_contracts(active_only=False)
        if str(r.get("contract_id", "")).upper() == contract_id.upper()
    ]
    return rows[0] if rows else None


def knowledge_graph() -> dict[str, Any]:
    # L5: prefer persisted GraphStore when configured / already synced
    try:
        from data_plane.graph.store import get_graph_store, graph_backend

        backend = graph_backend()
        if backend in {"sqlite", "neo4j"}:
            store = get_graph_store()
            data = store.load()
            if data.get("nodes"):
                return data
    except Exception:
        pass

    if data_mode() == "fixtures" or not _warehouse_ready():
        return fixtures.knowledge_graph()
    from data_plane.warehouse import db

    return {
        "nodes": db.query_dicts("SELECT id, type, label FROM kg_nodes"),
        "edges": db.query_dicts("SELECT source, target, type FROM kg_edges"),
        "backend": "duckdb",
    }


def customer_features(customer_id: str | None = None) -> list[dict[str, Any]]:
    if data_mode() == "fixtures" or not _warehouse_ready():
        return []
    from data_plane.warehouse import db

    if customer_id:
        return db.query_dicts("SELECT * FROM customer_features WHERE customer_id = ?", [customer_id])
    return db.query_dicts("SELECT * FROM customer_features")


def bank_statements(account_id: str | None = None) -> list[dict[str, Any]]:
    """Legacy helper — bank_statement rows (compat table)."""
    if not _warehouse_ready():
        return []
    from data_plane.warehouse import db

    if account_id:
        return db.query_dicts("SELECT * FROM bank_statements WHERE account_id = ?", [account_id])
    return db.query_dicts("SELECT * FROM bank_statements")


def portal_extracts(
    *,
    portal_id: str | None = None,
    extract_type: str | None = None,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    """Canonical multi-portal extracts (bank, SageSure-like, payer, etc.)."""
    if not _warehouse_ready():
        return []
    from data_plane.warehouse import db

    sql = "SELECT * FROM portal_extracts WHERE 1=1"
    params: list[Any] = []
    if portal_id:
        sql += " AND portal_id = ?"
        params.append(portal_id)
    if extract_type:
        sql += " AND extract_type = ?"
        params.append(extract_type)
    if entity_id:
        sql += " AND entity_id = ?"
        params.append(entity_id)
    sql += " ORDER BY ingested_at DESC"
    return db.query_dicts(sql, params)


def source_label() -> str:
    mode = data_mode()
    if mode == "bigquery":
        from data_plane.warehouse.bq_adapter import bq_ping

        ping = bq_ping()
        return "bigquery" if ping.get("ok") else "bigquery:fallback_duckdb"
    if mode == "warehouse" and _warehouse_ready():
        return "warehouse:duckdb"
    return "fixture:json"
