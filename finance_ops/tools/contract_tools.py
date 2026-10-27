from __future__ import annotations

from typing import Any

from data_plane import repository as repo
from finance_ops.lib.evidence import record_evidence


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in row.items()}


def lookup_contract(contract_id: str) -> dict[str, Any]:
    contract_id = contract_id.strip().upper()
    match = repo.get_contract(contract_id)
    result = (
        {"status": "not_found", "contract_id": contract_id, "needs_review": True}
        if not match
        else {"status": "success", "contract": _clean(match), "needs_review": False}
    )
    result["evidence"] = record_evidence(
        agent="contracts_agent", action="lookup_contract",
        inputs={"contract_id": contract_id}, outputs=result,
        sources=[repo.source_label()] if match else [],
    )
    return result


def lookup_customer_contract(customer_id: str) -> dict[str, Any]:
    customer_id = customer_id.strip().upper()
    rows = [_clean(r) for r in repo.list_contracts(customer_id=customer_id, active_only=True)]
    result = {
        "status": "success" if rows else "not_found", "customer_id": customer_id,
        "contracts": rows, "needs_review": len(rows) == 0,
    }
    result["evidence"] = record_evidence(
        agent="contracts_agent", action="lookup_customer_contract",
        inputs={"customer_id": customer_id}, outputs={"count": len(rows)},
        sources=[repo.source_label()],
    )
    return result
