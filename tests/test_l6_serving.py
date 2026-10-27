from __future__ import annotations

from fastapi.testclient import TestClient
from pipelines.batch.ingest import ingest_batch


def test_health_and_bootstrap() -> None:
    from finance_ops.serving import app

    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    boot = client.post("/v1/bootstrap")
    assert boot.status_code == 200
    body = boot.json()
    assert body["status"] == "success"
    assert body["vectors"]["count"] >= 1

    aging = client.post("/v1/aging", json={"customer_id": "CUST-ACME"})
    assert aging.status_code == 200
    assert aging.json()["invoice_count"] == 2

    search = client.post("/v1/search_policies", json={"query": "collections past due"})
    assert search.status_code == 200
    assert search.json()["hits"]


def test_status_endpoint() -> None:
    ingest_batch(run_id="l6-status-batch")
    from finance_ops.serving import app

    client = TestClient(app)
    resp = client.get("/v1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "warehouse" in data
    assert "vectors" in data
    assert "graph" in data
