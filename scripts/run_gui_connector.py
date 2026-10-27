#!/usr/bin/env python3
"""Start mock portal, Playwright download → incoming/legacy_bank → portal_extracts."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from gui_connectors.agent.playwright_connector import download_bank_statement
    from gui_connectors.ingest.portal_ingest import (
        ingest_portal_csv,
        process_incoming,
        stage_file_to_incoming,
    )
    from gui_connectors.mock_portal.server import serve
    from pipelines.batch.ingest import ingest_batch

    ingest_batch(run_id="pre-gui-batch")

    httpd = serve("127.0.0.1", 8765)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    print("Portal: http://127.0.0.1:8765/")

    try:
        gui = download_bank_statement(portal_url="http://127.0.0.1:8765/")
        print(json.dumps(gui, indent=2))
        if gui.get("status") != "success":
            return 1
        staged = stage_file_to_incoming("legacy_bank", gui["downloaded_file"])
        print(f"Staged: {staged}")
        ingest = ingest_portal_csv("legacy_bank", staged, extract_type="bank_statement")
        print(json.dumps(ingest, indent=2))
        watcher = process_incoming("legacy_bank")
        print(json.dumps(watcher, indent=2))
        ok = ingest.get("status") == "success" and ingest.get("rows", 0) >= 1
        print("GUI connector:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
