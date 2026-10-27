"""Thin HubSpot CRM client — private-app token, retries, timeouts.

Token from HUBSPOT_ACCESS_TOKEN (or HUBSPOT_PRIVATE_APP_TOKEN) only.
Never log or return the token.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from finance_ops.runtime.circuit_breaker import DEFAULT_BREAKER, CircuitOpenError

_DEFAULT_BASE = "https://api.hubapi.com"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MAX_RETRIES = 3
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class HubSpotConfigError(RuntimeError):
    """Missing or invalid HubSpot configuration (fail closed)."""


class HubSpotAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def access_token() -> str:
    token = (
        os.getenv("HUBSPOT_ACCESS_TOKEN", "").strip()
        or os.getenv("HUBSPOT_PRIVATE_APP_TOKEN", "").strip()
    )
    if not token:
        raise HubSpotConfigError(
            "HUBSPOT_ACCESS_TOKEN (or HUBSPOT_PRIVATE_APP_TOKEN) is required"
        )
    return token


def client_secret() -> str:
    """App client secret for webhook v3 signature validation (D7)."""
    secret = os.getenv("HUBSPOT_CLIENT_SECRET", "").strip()
    if not secret:
        raise HubSpotConfigError("HUBSPOT_CLIENT_SECRET is required")
    return secret


class HubSpotClient:
    """Minimal CRM client. Callers must not print headers or token."""

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        breaker: Any = None,
    ) -> None:
        self._token = token if token is not None else access_token()
        self._base = (base_url or os.getenv("HUBSPOT_API_BASE", _DEFAULT_BASE)).rstrip("/")
        self._breaker = breaker if breaker is not None else DEFAULT_BREAKER

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        tool_name: str = "hubspot_request",
    ) -> dict[str, Any]:
        self._breaker.record_tool(tool_name)
        url = path if path.startswith("http") else f"{self._base}{path}"
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                with httpx.Client(timeout=_TIMEOUT) as client:
                    resp = client.request(
                        method.upper(),
                        url,
                        headers=self._headers(),
                        json=json_body,
                        params=params,
                    )
                if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.5 * (2**attempt)
                    time.sleep(min(delay, 8.0))
                    continue
                if resp.status_code >= 400:
                    # Never include response body secrets; keep short message
                    raise HubSpotAPIError(
                        f"HubSpot HTTP {resp.status_code}",
                        status_code=resp.status_code,
                    )
                if not resp.content:
                    return {}
                data = resp.json()
                return data if isinstance(data, dict) else {"data": data}
            except CircuitOpenError:
                raise
            except HubSpotAPIError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise HubSpotAPIError(f"HubSpot request failed: {exc}") from exc
        raise HubSpotAPIError(f"HubSpot request failed: {last_exc}")

    def get_object(self, object_type: str, object_id: str, *, properties: list[str] | None = None) -> dict[str, Any]:
        params = None
        if properties:
            params = {"properties": ",".join(properties)}
        return self.request(
            "GET",
            f"/crm/v3/objects/{object_type}/{object_id}",
            params=params,
            tool_name=f"hubspot_get_{object_type}",
        )

    def search_objects(
        self,
        object_type: str,
        *,
        filter_groups: list[dict[str, Any]],
        properties: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "filterGroups": filter_groups,
            "limit": max(1, min(int(limit), 100)),
        }
        if properties:
            body["properties"] = properties
        return self.request(
            "POST",
            f"/crm/v3/objects/{object_type}/search",
            json_body=body,
            tool_name=f"hubspot_search_{object_type}",
        )

    def list_associations(
        self, from_type: str, from_id: str, to_type: str
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/crm/v4/objects/{from_type}/{from_id}/associations/{to_type}",
            tool_name=f"hubspot_assoc_{from_type}_{to_type}",
        )

    def create_object(self, object_type: str, properties: dict[str, Any]) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/crm/v3/objects/{object_type}",
            json_body={"properties": properties},
            tool_name=f"hubspot_create_{object_type}",
        )


def get_client() -> HubSpotClient:
    return HubSpotClient()
