"""Back-compat wrapper — prefer gui_connectors.ingest.portal_ingest."""

from __future__ import annotations

from gui_connectors.ingest.portal_ingest import ingest_bank_statement_csv, ingest_portal_csv

__all__ = ["ingest_bank_statement_csv", "ingest_portal_csv"]
