"""HubSpot webhook v3 signature validation + deal-keyed durable kickoff (D7)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from finance_ops.integrations.hubspot_client import HubSpotConfigError, client_secret

# HubSpot docs: reject timestamps older than 5 minutes.
_MAX_SKEW_MS = 5 * 60 * 1000

_URI_DECODE = (
    ("%3A", ":"),
    ("%2F", "/"),
    ("%3F", "?"),
    ("%40", "@"),
    ("%21", "!"),
    ("%24", "$"),
    ("%27", "'"),
    ("%28", "("),
    ("%29", ")"),
    ("%2A", "*"),
    ("%2C", ","),
    ("%3B", ";"),
)


def decode_hubspot_uri(uri: str) -> str:
    out = uri
    for enc, dec in _URI_DECODE:
        out = out.replace(enc, dec)
        out = out.replace(enc.lower(), dec)
    return out


def validate_signature_v3(
    *,
    method: str,
    full_uri: str,
    body: bytes | str,
    timestamp_ms: str | int,
    signature: str,
    secret: str | None = None,
    now_ms: int | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). Fail closed on missing/expired/mismatched signature."""
    try:
        secret = secret if secret is not None else client_secret()
    except HubSpotConfigError as exc:
        return False, f"config:{exc}"
    if not signature or timestamp_ms is None or timestamp_ms == "":
        return False, "missing_signature_or_timestamp"
    try:
        ts = int(timestamp_ms)
    except (TypeError, ValueError):
        return False, "invalid_timestamp"
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    if abs(now - ts) > _MAX_SKEW_MS:
        return False, "timestamp_outside_replay_window"
    raw_body = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
    uri = decode_hubspot_uri(full_uri)
    raw = f"{method.upper()}{uri}{raw_body}{ts}"
    digest = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    if not hmac.compare_digest(expected, signature):
        return False, "signature_mismatch"
    return True, "ok"


def extract_deal_id(payload: Any) -> str | None:
    """Best-effort deal id from HubSpot webhook event list or object."""
    if isinstance(payload, list):
        for event in payload:
            deal = extract_deal_id(event)
            if deal:
                return deal
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("objectId", "object_id", "dealId", "deal_id"):
        val = payload.get(key)
        if val is not None and str(val).strip():
            # Prefer deal-typed events
            obj_type = str(payload.get("objectType") or payload.get("subscriptionType") or "")
            if "deal" in obj_type.lower() or key.lower().startswith("deal"):
                return str(val).strip()
    # propertyChange / generic
    if str(payload.get("subscriptionType") or "").lower().startswith("deal."):
        oid = payload.get("objectId")
        if oid is not None:
            return str(oid).strip()
    nested = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
    for key in ("hs_object_id", "dealId"):
        if nested.get(key):
            return str(nested[key]).strip()
    return None


def start_deal_workflow(deal_id: str, *, event: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start or resume a durable portal-reconcile-shaped DAG keyed by HubSpot deal id."""
    from finance_ops.runtime.durable import DurableWorkflow, deal_closed_won_handlers

    deal_id = deal_id.strip()
    if not deal_id:
        return {"status": "error", "error": "deal_id required", "needs_review": True}

    from datetime import datetime, timezone

    from finance_ops.runtime.durable import StepStatus, WorkflowState, WorkflowStep

    wf = DurableWorkflow()
    # Stable run id so retries / duplicate webhooks resume the same checkpoint.
    run_id = f"WF-HS-DEAL-{deal_id}"
    path = wf._path(run_id)
    handlers = deal_closed_won_handlers()
    meta = {
        "hubspot_deal_id": deal_id,
        "source": "hubspot_webhook",
        "event_type": (event or {}).get("subscriptionType"),
    }
    if path.is_file():
        state = wf.resume(run_id, handlers, max_retries=2)
    else:
        now = datetime.now(timezone.utc).isoformat()
        state = WorkflowState(
            run_id=run_id,
            name="hubspot_deal_closed_won",
            status=StepStatus.pending,
            steps=[WorkflowStep(name=n) for n in handlers.keys()],
            created_at=now,
            updated_at=now,
            meta=meta,
        )
        wf.save(state)
        state = wf.run(handlers, state=state, max_retries=2)
    return {
        "status": "success" if state.status.value == "success" else state.status.value,
        "run_id": state.run_id,
        "deal_id": deal_id,
        "workflow_status": state.status.value,
        "steps": [s.model_dump() for s in state.steps],
        "needs_review": state.status.value != "success",
    }


def parse_webhook_body(raw: bytes | str) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8")
    else:
        text = str(raw)
    if not text.strip():
        return []
    return json.loads(text)
