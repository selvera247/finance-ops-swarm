"""Agent-callable wrappers for GUI extract + portal_extracts reads."""

from __future__ import annotations

from typing import Any

from finance_ops.lib.evidence import record_evidence
from finance_ops.runtime.circuit_breaker import DEFAULT_BREAKER, CircuitOpenError


def _tool(name: str) -> None:
    DEFAULT_BREAKER.record_tool(name)


def fetch_legacy_bank_statement() -> dict[str, Any]:
    """Playwright: mock bank portal → data/incoming/legacy_bank → portal_extracts."""
    from gui_connectors.agent.playwright_connector import download_bank_statement
    from gui_connectors.ingest.portal_ingest import (
        ingest_portal_csv,
        process_incoming,
        stage_file_to_incoming,
    )

    try:
        _tool("fetch_legacy_bank_statement")
    except CircuitOpenError as exc:
        return {"status": "circuit_open", "error": str(exc), "needs_review": True}

    gui = download_bank_statement()
    if gui.get("status") != "success" or not gui.get("downloaded_file"):
        result = {
            "status": "error",
            "gui": gui,
            "needs_review": True,
            "hint": "Start mock portal via scripts/run_gui_connector.py",
        }
        result["evidence"] = record_evidence(
            agent="coordinator",
            action="fetch_legacy_bank_statement",
            inputs={},
            outputs=result,
            sources=["gui:legacy_bank"],
        )
        return result

    staged = stage_file_to_incoming("legacy_bank", gui["downloaded_file"])
    ingest = ingest_portal_csv("legacy_bank", staged, extract_type="bank_statement")
    # Also drain any other queued CSVs for this portal
    watcher = process_incoming("legacy_bank")
    result = {
        "status": "success" if ingest.get("status") == "success" else "error",
        "gui": gui,
        "staged": str(staged),
        "ingest": ingest,
        "incoming_watcher": watcher,
        "needs_review": False,
    }
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="fetch_legacy_bank_statement",
        inputs={},
        outputs={"rows": ingest.get("rows"), "batch_id": ingest.get("batch_id")},
        sources=["gui:legacy_bank", f"incoming:{staged}"],
    )
    return result


def process_portal_incoming(portal_id: str | None = None) -> dict[str, Any]:
    """Ingest any CSVs waiting in data/incoming/<portal_id>/ (drop-zone watcher)."""
    from gui_connectors.ingest.portal_ingest import process_incoming

    try:
        _tool("process_portal_incoming")
    except CircuitOpenError as exc:
        return {"status": "circuit_open", "error": str(exc), "needs_review": True}

    watcher = process_incoming(portal_id)
    result = {**watcher, "needs_review": watcher.get("status") != "success"}
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="process_portal_incoming",
        inputs={"portal_id": portal_id},
        outputs={"files_processed": watcher.get("files_processed")},
        sources=[f"incoming:{portal_id or '*'}"],
    )
    return result


def list_portal_extracts(
    portal_id: str | None = None,
    extract_type: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """List rows from the canonical portal_extracts table."""
    from data_plane import repository as repo

    try:
        _tool("list_portal_extracts")
    except CircuitOpenError as exc:
        return {"status": "circuit_open", "error": str(exc), "needs_review": True}

    rows = repo.portal_extracts(
        portal_id=portal_id, extract_type=extract_type, entity_id=entity_id
    )
    clean = [
        {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows
    ]
    result = {
        "status": "success",
        "count": len(clean),
        "extracts": clean,
        "needs_review": len(clean) == 0,
    }
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="list_portal_extracts",
        inputs={
            "portal_id": portal_id,
            "extract_type": extract_type,
            "entity_id": entity_id,
        },
        outputs={"count": len(clean)},
        sources=[repo.source_label() + ":portal_extracts"],
    )
    return result


def list_bank_statements(account_id: str | None = None) -> dict[str, Any]:
    """Back-compat: bank portal extracts filtered to bank_statement / entity_id."""
    return list_portal_extracts(
        portal_id="legacy_bank",
        extract_type="bank_statement",
        entity_id=account_id,
    )
