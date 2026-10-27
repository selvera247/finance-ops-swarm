from __future__ import annotations

import threading
import time

import pytest

from data_plane import repository as repo
from gui_connectors.agent.playwright_connector import download_bank_statement
from gui_connectors.ingest.portal_ingest import (
    ingest_portal_csv,
    stage_file_to_incoming,
)
from gui_connectors.mock_portal.server import serve
from pipelines.batch.ingest import ingest_batch


@pytest.fixture(scope="module")
def portal_server():
    httpd = serve("127.0.0.1", 8765)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.4)
    yield "http://127.0.0.1:8765/"
    httpd.shutdown()


def test_playwright_download_stages_and_ingests_portal_extracts(portal_server):
    ingest_batch(run_id="gui-test-batch")
    gui = download_bank_statement(portal_url=portal_server, headless=True)
    assert gui["status"] == "success", gui
    assert gui["downloaded_file"]
    assert "login_ok" in gui["steps"]

    staged = stage_file_to_incoming("legacy_bank", gui["downloaded_file"])
    ingest = ingest_portal_csv("legacy_bank", staged, extract_type="bank_statement")
    assert ingest["status"] == "success"
    assert ingest["rows"] >= 3

    extracts = repo.portal_extracts(portal_id="legacy_bank", extract_type="bank_statement")
    assert len(extracts) >= 3
    assert len(repo.bank_statements("ACC-1001")) >= 3
