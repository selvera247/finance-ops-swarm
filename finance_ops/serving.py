"""L6 Cloud Run HTTP surface — health + platform status + tool smokes.

Run locally:
  uvicorn finance_ops.serving:app --host 0.0.0.0 --port 8080

Cloud Run sets PORT; see deploy/entrypoint.sh.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

app = FastAPI(title="finance_ops", version="0.5.0")


def _require_governance_token(
    authorization: str | None = None,
    x_governance_token: str | None = None,
) -> None:
    """Fail closed: sweep/revoke HTTP routes need FINANCE_OPS_GOVERNANCE_TOKEN."""
    expected = os.getenv("FINANCE_OPS_GOVERNANCE_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="governance token not configured (FINANCE_OPS_GOVERNANCE_TOKEN)",
        )
    provided = (x_governance_token or "").strip()
    if not provided and authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="unauthorized governance call")


class SearchBody(BaseModel):
    query: str = "collections escalation past due"
    top_k: int = 3


class AgingBody(BaseModel):
    customer_id: str = "CUST-ACME"


class ApprovalBody(BaseModel):
    kind: str = "write_off"
    amount: float = 125.0
    summary: str = "Cloud Run HITL smoke"
    related_ids: str = ""


class PaymentMatchBody(BaseModel):
    payment_id: str = "PAY-1001"
    invoice_id: str = ""


class DecideBody(BaseModel):
    approval_id: str
    decision: str = "approved"
    resume_token: str = ""
    actor: str = "api"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "finance_ops",
        "model": os.getenv("FINANCE_OPS_MODEL", "gemini-3.1-flash-lite"),
        "data_mode": os.getenv("FINANCE_OPS_DATA_MODE", "warehouse"),
    }


@app.get("/v1/status")
def platform_status() -> dict[str, Any]:
    from finance_ops.tools.bigquery_tools import bigquery_status
    from finance_ops.tools.graph_tools import graph_status
    from data_plane.vectors.embed import vertex_vector_status

    return {
        "status": "success",
        "warehouse": bigquery_status(),
        "vectors": vertex_vector_status(),
        "graph": graph_status(),
    }


@app.post("/v1/search_policies")
def api_search_policies(body: SearchBody) -> dict[str, Any]:
    from finance_ops.tools.rag_tools import search_policies

    return search_policies(body.query, top_k=body.top_k)


@app.post("/v1/aging")
def api_aging(body: AgingBody) -> dict[str, Any]:
    from finance_ops.tools.invoice_tools import aging_summary

    return aging_summary(body.customer_id)


@app.post("/v1/request_approval")
def api_request_approval(body: ApprovalBody) -> dict[str, Any]:
    from finance_ops.tools.runtime_tools import request_approval

    return request_approval(
        kind=body.kind,
        amount=body.amount,
        summary=body.summary,
        related_ids=body.related_ids,
    )


@app.post("/v1/suggest_payment_match")
def api_suggest_payment_match(body: PaymentMatchBody) -> dict[str, Any]:
    from finance_ops.tools.payment_tools import suggest_payment_match

    return suggest_payment_match(body.payment_id)


@app.post("/v1/request_cash_app_approval")
def api_request_cash_app_approval(body: PaymentMatchBody) -> dict[str, Any]:
    from finance_ops.tools.payment_tools import request_cash_app_approval

    return request_cash_app_approval(body.payment_id, invoice_id=body.invoice_id or "")


@app.post("/v1/decide_approval")
def api_decide_approval(body: DecideBody) -> dict[str, Any]:
    from finance_ops.tools.runtime_tools import decide_approval

    return decide_approval(
        body.approval_id,
        body.decision,
        resume_token=body.resume_token,
        actor=body.actor,
    )


@app.post("/v1/bootstrap")
def api_bootstrap() -> dict[str, Any]:
    """Idempotent warehouse + vector + graph sync for cold Cloud Run instances."""
    from data_plane.graph.sync import sync_knowledge_graph
    from data_plane.vectors.embed import build_policy_index
    from pipelines.batch.ingest import ingest_batch

    batch = ingest_batch(run_id="cloudrun-bootstrap")
    vectors = build_policy_index()
    graph = sync_knowledge_graph()
    return {"status": "success", "batch": batch, "vectors": vectors, "graph": graph}


@app.post("/v1/governance/sweep")
def api_governance_sweep(
    authorization: str | None = Header(default=None),
    x_governance_token: str | None = Header(default=None, alias="X-Governance-Token"),
) -> dict[str, Any]:
    """Cloud Scheduler target: TTL + eval lifecycle sweep (retire / deprecate / revoke).

    Auth required — not an agent tool. Send `Authorization: Bearer <token>` or
    `X-Governance-Token` matching FINANCE_OPS_GOVERNANCE_TOKEN.
    """
    _require_governance_token(authorization, x_governance_token)
    from finance_ops.governance.registry import sweep_lifecycle

    return sweep_lifecycle()


@app.get("/v1/governance/agents")
def api_governance_agents(
    authorization: str | None = Header(default=None),
    x_governance_token: str | None = Header(default=None, alias="X-Governance-Token"),
) -> dict[str, Any]:
    _require_governance_token(authorization, x_governance_token)
    from finance_ops.governance.registry import list_agents

    return {"status": "success", "agents": list_agents(), "needs_review": False}


@app.post("/v1/hubspot/webhook")
async def api_hubspot_webhook(
    request: Request,
    x_hubspot_signature_v3: str | None = Header(default=None, alias="X-HubSpot-Signature-v3"),
    x_hubspot_request_timestamp: str | None = Header(
        default=None, alias="X-HubSpot-Request-Timestamp"
    ),
) -> dict[str, Any]:
    """D7 — HubSpot webhook: v3 signature + 5-min replay window; durable DAG by deal id."""
    from finance_ops.governance.audit import append_audit
    from finance_ops.integrations.hubspot_webhook import (
        extract_deal_id,
        parse_webhook_body,
        start_deal_workflow,
        validate_signature_v3,
    )

    raw = await request.body()
    # Full target URL as configured in HubSpot (override via env for local/ngrok).
    public_base = os.getenv("HITL_PUBLIC_BASE_URL", "").rstrip("/")
    if public_base:
        full_uri = f"{public_base}/v1/hubspot/webhook"
    else:
        full_uri = str(request.url)

    ok, reason = validate_signature_v3(
        method="POST",
        full_uri=full_uri,
        body=raw,
        timestamp_ms=x_hubspot_request_timestamp or "",
        signature=x_hubspot_signature_v3 or "",
    )
    if not ok:
        append_audit(
            event="hubspot_webhook",
            agent="serving",
            decision="deny",
            tool="hubspot_webhook",
            reason=reason,
        )
        raise HTTPException(status_code=401, detail=f"invalid_hubspot_signature:{reason}")

    try:
        payload = parse_webhook_body(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_json:{exc}") from exc

    deal_id = extract_deal_id(payload)
    if not deal_id:
        append_audit(
            event="hubspot_webhook",
            agent="serving",
            decision="ignore",
            tool="hubspot_webhook",
            reason="no_deal_id",
        )
        return {"status": "ignored", "reason": "no_deal_id", "needs_review": False}

    event = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(event, dict):
        event = {"objectId": deal_id}
    result = start_deal_workflow(deal_id, event=event)
    append_audit(
        event="hubspot_webhook",
        agent="serving",
        decision="allow",
        tool="hubspot_webhook",
        args={"deal_id": deal_id},
        reason=result.get("workflow_status"),
        extra={"run_id": result.get("run_id")},
    )
    return result
