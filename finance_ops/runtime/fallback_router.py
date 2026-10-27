"""#11 API/warehouse → browser fallback router."""

from __future__ import annotations

import time
from typing import Any, Callable

from finance_ops.runtime.circuit_breaker import DEFAULT_BREAKER, CircuitOpenError


def _warehouse_portal_rows(
    portal_id: str,
    *,
    entity_id: str | None = None,
    extract_type: str | None = None,
    min_rows: int = 1,
) -> list[dict[str, Any]]:
    from data_plane import repository as repo

    rows = repo.portal_extracts(
        portal_id=portal_id, extract_type=extract_type, entity_id=entity_id
    )
    return rows if len(rows) >= min_rows else []


def _gui_pull_legacy_bank() -> dict[str, Any]:
    """Spawn headless browser path for legacy bank portal."""
    from gui_connectors.agent.playwright_connector import download_bank_statement
    from gui_connectors.ingest.portal_ingest import (
        ingest_portal_csv,
        process_incoming,
        stage_file_to_incoming,
    )
    from gui_connectors.mock_portal.server import serve
    import threading

    # If portal not up, start ephemeral server (tests/scripts)
    httpd = None
    try:
        httpd = serve("127.0.0.1", 8765)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.25)
    except OSError:
        # Port already in use — assume portal is running
        httpd = None

    try:
        gui = download_bank_statement(portal_url="http://127.0.0.1:8765/")
        if gui.get("status") != "success" or not gui.get("downloaded_file"):
            return {"status": "error", "path": "browser", "gui": gui}
        staged = stage_file_to_incoming("legacy_bank", gui["downloaded_file"])
        ingest = ingest_portal_csv("legacy_bank", staged, extract_type="bank_statement")
        process_incoming("legacy_bank")
        return {
            "status": "success" if ingest.get("status") == "success" else "error",
            "path": "browser",
            "gui": gui,
            "ingest": ingest,
        }
    finally:
        if httpd is not None:
            httpd.shutdown()


def resolve_portal_data(
    portal_id: str = "legacy_bank",
    *,
    entity_id: str | None = None,
    extract_type: str | None = None,
    min_rows: int = 1,
    allow_browser_fallback: bool = True,
    api_lookup: Callable[[], list[dict[str, Any]]] | None = None,
    api_timeout_seconds: float = 2.0,
    breaker=DEFAULT_BREAKER,
) -> dict[str, Any]:
    """Try warehouse (and optional API); on miss/timeout/error, spawn browser GUI pull.

    Returns a structured result with which path served the data.
    """
    breaker.record_tool("resolve_portal_data")
    breaker.enter("resolve_portal_data")
    try:
        # 1) Optional primary API
        api_error = None
        if api_lookup is not None:
            try:
                started = time.time()
                rows = api_lookup()
                if time.time() - started > api_timeout_seconds:
                    raise TimeoutError("api_lookup exceeded timeout")
                if rows and len(rows) >= min_rows:
                    return {
                        "status": "success",
                        "path": "api",
                        "portal_id": portal_id,
                        "count": len(rows),
                        "rows": rows,
                        "needs_review": False,
                    }
            except Exception as exc:  # noqa: BLE001
                api_error = str(exc)

        # 2) Warehouse / prior extracts
        try:
            rows = _warehouse_portal_rows(
                portal_id,
                entity_id=entity_id,
                extract_type=extract_type,
                min_rows=min_rows,
            )
            if rows:
                return {
                    "status": "success",
                    "path": "warehouse",
                    "portal_id": portal_id,
                    "count": len(rows),
                    "rows": rows,
                    "api_error": api_error,
                    "needs_review": False,
                }
        except Exception as exc:  # noqa: BLE001
            api_error = f"{api_error}; warehouse={exc}" if api_error else str(exc)

        # 3) Browser fallback (GUI unlock)
        if not allow_browser_fallback:
            return {
                "status": "not_found",
                "path": "none",
                "portal_id": portal_id,
                "api_error": api_error,
                "needs_review": True,
            }

        if portal_id != "legacy_bank":
            return {
                "status": "error",
                "path": "browser_unsupported",
                "portal_id": portal_id,
                "hint": "Browser fallback implemented for legacy_bank mock; drop CSV into data/incoming/<portal>/",
                "api_error": api_error,
                "needs_review": True,
            }

        browser = _gui_pull_legacy_bank()
        if browser.get("status") != "success":
            return {**browser, "api_error": api_error, "needs_review": True}

        rows = _warehouse_portal_rows(
            portal_id,
            entity_id=entity_id,
            extract_type=extract_type or "bank_statement",
            min_rows=min_rows,
        )
        return {
            "status": "success" if rows else "error",
            "path": "browser",
            "portal_id": portal_id,
            "count": len(rows),
            "rows": rows,
            "browser": browser,
            "api_error": api_error,
            "needs_review": not bool(rows),
        }
    except CircuitOpenError:
        raise
    finally:
        breaker.exit("resolve_portal_data")
