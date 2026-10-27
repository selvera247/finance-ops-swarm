"""HubSpot client + tools (D1) — mocked HTTP, fail-closed token, circuit guard."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from finance_ops.integrations.hubspot_client import (
    HubSpotAPIError,
    HubSpotClient,
    HubSpotConfigError,
    access_token,
)
from finance_ops.tools import hubspot_tools


@pytest.fixture(autouse=True)
def _no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("HUBSPOT_PRIVATE_APP_TOKEN", raising=False)


def test_access_token_fail_closed() -> None:
    with pytest.raises(HubSpotConfigError):
        access_token()


def test_get_company_denied_without_token() -> None:
    out = hubspot_tools.get_company("123")
    assert out["status"] == "denied"
    assert out["error"] == "hubspot_token_missing"


def test_get_company_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token-not-a-real-secret")

    class FakeClient:
        def get_object(self, object_type: str, object_id: str, *, properties=None):
            assert object_type == "companies"
            return {
                "id": object_id,
                "properties": {"name": "Acme", "domain": "acme.example"},
            }

    monkeypatch.setattr(hubspot_tools, "get_client", lambda: FakeClient())
    out = hubspot_tools.get_company("99")
    assert out["status"] == "success"
    assert out["company"]["properties"]["name"] == "Acme"
    assert out["evidence"]["evidence_id"]


def test_create_task_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token-not-a-real-secret")

    class FakeClient:
        def create_object(self, object_type: str, properties: dict[str, Any]):
            assert object_type == "tasks"
            assert "hs_task_subject" in properties
            return {"id": "task-1"}

    monkeypatch.setattr(hubspot_tools, "get_client", lambda: FakeClient())
    out = hubspot_tools.create_task("Follow up AR", body="see approval")
    assert out["status"] == "success"
    assert out["task_id"] == "task-1"


def test_client_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token-not-a-real-secret")
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, status: int, payload: dict | None = None):
            self.status_code = status
            self.headers = {"Retry-After": "0"}
            self.content = b"{}" if payload is not None else b"{}"
            self._payload = payload or {}

        def json(self):
            return self._payload

    def fake_request(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return FakeResp(429)
        return FakeResp(200, {"id": "1", "properties": {}})

    with patch("httpx.Client") as client_cls:
        inst = MagicMock()
        inst.__enter__.return_value = inst
        inst.__exit__.return_value = False
        inst.request.side_effect = fake_request
        client_cls.return_value = inst
        from finance_ops.runtime.circuit_breaker import CircuitBreaker

        c = HubSpotClient(
            token="test-token-not-a-real-secret",
            breaker=CircuitBreaker(max_tool_calls=100),
        )
        # Avoid real sleep during retry backoff
        with patch("finance_ops.integrations.hubspot_client.time.sleep"):
            out = c.request("GET", "/crm/v3/objects/companies/1", tool_name="t")
        assert out.get("id") == "1"
        assert calls["n"] >= 2


def test_client_maps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token-not-a-real-secret")

    class FakeResp:
        status_code = 404
        headers: dict = {}
        content = b"{}"

        def json(self):
            return {"message": "missing"}

    with patch("httpx.Client") as client_cls:
        inst = MagicMock()
        inst.__enter__.return_value = inst
        inst.__exit__.return_value = False
        inst.request.return_value = FakeResp()
        client_cls.return_value = inst
        from finance_ops.runtime.circuit_breaker import CircuitBreaker

        c = HubSpotClient(token="t", breaker=CircuitBreaker(max_tool_calls=100))
        with pytest.raises(HubSpotAPIError) as ei:
            c.request("GET", "/crm/v3/objects/companies/nope")
        assert ei.value.status_code == 404
