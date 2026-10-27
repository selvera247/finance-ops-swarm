"""Read-only MCP server — warehouse / BQ tools for external MCP clients.

Run:
  PYTHONPATH=. python -m finance_ops.mcp

Does NOT expose apply_payment_match, HITL approve, or GUI browser pulls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[2]
    for path in (root / "finance_ops" / ".env", root / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


def _json(data: Any) -> str:
    from finance_ops.runtime.sanitize import sanitize_for_export

    return json.dumps(sanitize_for_export(data), indent=2, default=str)


def build_server() -> MCPServer:
    _load_dotenv()
    server = MCPServer(
        "finance_ops_readonly",
        instructions=(
            "Read-only finance ops tools over the warehouse/BigQuery data plane. "
            "Use for aging, unmatched cash, match suggestions, policies, and evidence. "
            "Do not expect write/HITL/apply tools here — those stay in ADK / HITL."
        ),
    )

    @server.tool()
    def aging_summary(customer_id: str = "CUST-ACME") -> str:
        """Open AR aging buckets for a customer (e.g. CUST-ACME or C-1042)."""
        from finance_ops.tools.invoice_tools import aging_summary as _fn

        return _json(_fn(customer_id))

    @server.tool()
    def list_open_invoices(customer_id: str = "") -> str:
        """List open/past_due invoices; optional customer_id filter."""
        from finance_ops.tools.invoice_tools import list_open_invoices as _fn

        return _json(_fn(customer_id or None))

    @server.tool()
    def lookup_invoice(invoice_id: str) -> str:
        """Lookup one invoice by id (e.g. INV-1001 or INV-84219)."""
        from finance_ops.tools.invoice_tools import lookup_invoice as _fn

        return _json(_fn(invoice_id))

    @server.tool()
    def list_unmatched_payments(customer_id: str = "") -> str:
        """List unmatched/partial payments; optional customer_id (e.g. C-1042)."""
        from finance_ops.tools.payment_tools import list_unmatched_payments as _fn

        return _json(_fn(customer_id or None))

    @server.tool()
    def lookup_payment(payment_id: str) -> str:
        """Lookup one payment by id (e.g. PAY-1001)."""
        from finance_ops.tools.payment_tools import lookup_payment as _fn

        return _json(_fn(payment_id))

    @server.tool()
    def suggest_payment_match(payment_id: str) -> str:
        """Suggest invoice match candidates for a payment (does not apply the match)."""
        from finance_ops.tools.payment_tools import suggest_payment_match as _fn

        return _json(_fn(payment_id))

    @server.tool()
    def search_policies(query: str = "collections escalation", top_k: int = 3) -> str:
        """Search policy / RAG corpus for collections or recon guidance."""
        from finance_ops.tools.rag_tools import search_policies as _fn

        return _json(_fn(query, top_k=top_k))

    @server.tool()
    def get_evidence(evidence_id: str) -> str:
        """Fetch a stored evidence record by EVD-… id."""
        from finance_ops.tools.governance_tools import get_evidence as _fn

        return _json(_fn(evidence_id))

    @server.tool()
    def recent_evidence(limit: int = 10) -> str:
        """List recent evidence records (audit trail)."""
        from finance_ops.tools.governance_tools import recent_evidence as _fn

        return _json(_fn(limit=limit))

    @server.tool()
    def bigquery_status() -> str:
        """Report data_mode, BigQuery ping, and active warehouse source."""
        from finance_ops.tools.bigquery_tools import bigquery_status as _fn

        return _json(_fn())

    @server.tool()
    def graph_neighborhood(entity_id: str, max_hops: int = 2) -> str:
        """Read-only knowledge-graph neighborhood for an entity id."""
        from finance_ops.tools.graph_tools import graph_neighborhood as _fn

        return _json(_fn(entity_id, max_hops=max_hops))

    return server


# Module-level server for `python -m finance_ops.mcp` and tests
mcp = build_server()


def main() -> None:
    transport = os.getenv("FINANCE_OPS_MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # Future: sse / http — stdio is the supported local Cursor path
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
