from __future__ import annotations

from typing import Any

from data_plane import repository as repo
from finance_ops.lib.evidence import record_evidence


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in row.items()}


def lookup_invoice(invoice_id: str) -> dict[str, Any]:
    invoice_id = invoice_id.strip().upper()
    match = repo.get_invoice(invoice_id)
    result = (
        {"status": "not_found", "invoice_id": invoice_id, "needs_review": True}
        if not match
        else {"status": "success", "invoice": _clean(match), "needs_review": False}
    )
    result["evidence"] = record_evidence(
        agent="invoice_agent", action="lookup_invoice",
        inputs={"invoice_id": invoice_id}, outputs=result,
        sources=[repo.source_label()] if match else [],
    )
    return result


def list_open_invoices(customer_id: str | None = None) -> dict[str, Any]:
    rows = [_clean(r) for r in repo.list_invoices(customer_id=customer_id, open_only=True)]
    result = {"status": "success", "count": len(rows), "invoices": rows, "needs_review": False}
    result["evidence"] = record_evidence(
        agent="invoice_agent", action="list_open_invoices",
        inputs={"customer_id": customer_id}, outputs={"count": len(rows)},
        sources=[repo.source_label()],
    )
    return result


def aging_summary(customer_id: str | None = None) -> dict[str, Any]:
    rows = repo.list_invoices(customer_id=customer_id, open_only=True)
    buckets: dict[str, float] = {}
    for row in rows:
        buckets[str(row["aging_bucket"])] = buckets.get(str(row["aging_bucket"]), 0.0) + float(row["amount"])
    result = {
        "status": "success", "customer_id": customer_id, "total_open": sum(buckets.values()),
        "buckets": buckets, "invoice_count": len(rows), "needs_review": False,
    }
    result["evidence"] = record_evidence(
        agent="invoice_agent", action="aging_summary",
        inputs={"customer_id": customer_id}, outputs=result, sources=[repo.source_label()],
    )
    return result
