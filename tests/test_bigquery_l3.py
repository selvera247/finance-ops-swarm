"""L3 BigQuery mode routing — falls back to DuckDB without live GCP."""

from __future__ import annotations

import os

from finance_ops.lib.fixtures import reload_fixtures
from finance_ops.tools.bigquery_tools import bigquery_status
from finance_ops.tools.invoice_tools import aging_summary
from pipelines.batch.ingest import ingest_batch


def setup_function() -> None:
    reload_fixtures()
    ingest_batch(run_id="bq-l3-batch")


def test_bq_ping_without_project(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    from data_plane.warehouse.bq_adapter import bq_ping

    ping = bq_ping()
    assert ping["ok"] is False
    assert ping["mode"] == "fallback_duckdb"


def test_repository_bigquery_mode_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_DATA_MODE", "bigquery")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)

    from data_plane import repository as repo

    rows = repo.list_invoices(customer_id="CUST-ACME", open_only=True)
    assert len(rows) >= 2
    assert "bigquery" in repo.source_label()


def test_aging_works_in_bigquery_mode_via_fallback(monkeypatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_DATA_MODE", "bigquery")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    result = aging_summary("CUST-ACME")
    assert result["invoice_count"] == 2
    assert result["total_open"] == 16700.0


def test_bigquery_status_reports_fallback(monkeypatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_DATA_MODE", "bigquery")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    status = bigquery_status()
    assert status["data_mode"] == "bigquery"
    assert status["bigquery"]["ok"] is False
    assert status["active_source"] == "duckdb_fallback"
    assert status["needs_review"] is True
