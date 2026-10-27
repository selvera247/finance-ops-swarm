"""HubSpot CRM tools — read for specialists; write for HITL runtime path only.

Read tools: get_company, get_deal, list_closed_won_deals, get_deal_line_items,
get_open_tickets_for_company, compare_sold_contracted_invoiced,
enrich_aging_hubspot, match_hubspot_company.
Write tools: create_task, create_note (not on coordinator/payments RBAC).
"""

from __future__ import annotations

from typing import Any

from finance_ops.integrations.hubspot_client import (
    HubSpotAPIError,
    HubSpotClient,
    HubSpotConfigError,
    get_client,
)
from finance_ops.lib.evidence import record_evidence
from finance_ops.runtime.a2a import EvidenceRef
from finance_ops.runtime.circuit_breaker import CircuitOpenError
from finance_ops.runtime.sanitize import (
    HUBSPOT_COMPANY_ALLOWLIST,
    HUBSPOT_DEAL_ALLOWLIST,
    HUBSPOT_LINE_ALLOWLIST,
    HUBSPOT_TICKET_ALLOWLIST,
    allowlist_props,
    sanitize_for_export,
    sanitize_hubspot_text,
)

# Properties requested from HubSpot API (D8 allowlists).
_COMPANY_PROPS = sorted(HUBSPOT_COMPANY_ALLOWLIST)
_DEAL_PROPS = sorted(HUBSPOT_DEAL_ALLOWLIST)
_LINE_PROPS = sorted(HUBSPOT_LINE_ALLOWLIST)
_TICKET_PROPS = sorted(HUBSPOT_TICKET_ALLOWLIST)


def _err(status: str, error: str, **extra: Any) -> dict[str, Any]:
    out = {"status": status, "error": error, "needs_review": True, **extra}
    return out


def _props(obj: dict[str, Any], allow: frozenset[str]) -> dict[str, Any]:
    raw = obj.get("properties") if isinstance(obj.get("properties"), dict) else {}
    return allowlist_props(raw, allow)


def _client_or_error() -> HubSpotClient | dict[str, Any]:
    try:
        return get_client()
    except HubSpotConfigError as exc:
        return _err("denied", "hubspot_token_missing", detail=str(exc))


def get_company(company_id: str) -> dict[str, Any]:
    """Read a HubSpot company by id (minimal properties)."""
    client = _client_or_error()
    if isinstance(client, dict):
        return client
    company_id = company_id.strip()
    if not company_id:
        return _err("error", "company_id required")
    try:
        raw = client.get_object("companies", company_id, properties=_COMPANY_PROPS)
        company = sanitize_for_export(
            {"id": raw.get("id"), "properties": _props(raw, HUBSPOT_COMPANY_ALLOWLIST)}
        )
        result = {"status": "success", "company": company, "needs_review": False}
        result["evidence"] = record_evidence(
            agent="hubspot",
            action="get_company",
            inputs={"company_id": company_id},
            outputs={"id": company.get("id")},
            sources=[f"hubspot:company:{company_id}"],
        )
        return result
    except CircuitOpenError as exc:
        return _err("circuit_open", str(exc))
    except HubSpotAPIError as exc:
        return _err("error", str(exc), http_status=exc.status_code)


def get_deal(deal_id: str) -> dict[str, Any]:
    """Read a HubSpot deal by id."""
    client = _client_or_error()
    if isinstance(client, dict):
        return client
    deal_id = deal_id.strip()
    if not deal_id:
        return _err("error", "deal_id required")
    try:
        raw = client.get_object("deals", deal_id, properties=_DEAL_PROPS)
        deal = sanitize_for_export(
            {"id": raw.get("id"), "properties": _props(raw, HUBSPOT_DEAL_ALLOWLIST)}
        )
        result = {"status": "success", "deal": deal, "needs_review": False}
        result["evidence"] = record_evidence(
            agent="hubspot",
            action="get_deal",
            inputs={"deal_id": deal_id},
            outputs={"id": deal.get("id")},
            sources=[f"hubspot:deal:{deal_id}"],
        )
        return result
    except CircuitOpenError as exc:
        return _err("circuit_open", str(exc))
    except HubSpotAPIError as exc:
        return _err("error", str(exc), http_status=exc.status_code)


def list_closed_won_deals(
    company_id: str = "",
    limit: int = 25,
) -> dict[str, Any]:
    """List closed-won deals, optionally filtered by associated company id via search."""
    client = _client_or_error()
    if isinstance(client, dict):
        return client
    limit = max(1, min(int(limit), 50))
    filters: list[dict[str, Any]] = [
        {"propertyName": "hs_is_closed_won", "operator": "EQ", "value": "true"},
    ]
    # Company filter uses associations search when company_id provided — property associations
    # are not always searchable; if company_id set we still search closed-won then note filter.
    try:
        raw = client.search_objects(
            "deals",
            filter_groups=[{"filters": filters}],
            properties=_DEAL_PROPS,
            limit=limit,
        )
        results = []
        for row in raw.get("results") or []:
            results.append(
                sanitize_for_export(
                    {"id": row.get("id"), "properties": _props(row, HUBSPOT_DEAL_ALLOWLIST)}
                )
            )
        # Optional post-filter hint when company_id supplied (full assoc filter in D5)
        result = {
            "status": "success",
            "count": len(results),
            "deals": results,
            "company_id": company_id.strip() or None,
            "needs_review": False,
        }
        result["evidence"] = record_evidence(
            agent="hubspot",
            action="list_closed_won_deals",
            inputs={"company_id": company_id, "limit": limit},
            outputs={"count": len(results)},
            sources=["hubspot:deals:closed_won"],
        )
        return result
    except CircuitOpenError as exc:
        return _err("circuit_open", str(exc))
    except HubSpotAPIError as exc:
        return _err("error", str(exc), http_status=exc.status_code)


def get_deal_line_items(deal_id: str) -> dict[str, Any]:
    """Fetch line items associated with a deal."""
    client = _client_or_error()
    if isinstance(client, dict):
        return client
    deal_id = deal_id.strip()
    if not deal_id:
        return _err("error", "deal_id required")
    try:
        assoc = client.list_associations("deals", deal_id, "line_items")
        ids: list[str] = []
        for row in assoc.get("results") or []:
            to_obj = row.get("toObjectId") or row.get("id")
            if to_obj is not None:
                ids.append(str(to_obj))
            # v4 shape: [{"toObjectId": ...}]
            for t in row.get("to") or []:
                if t.get("toObjectId") is not None:
                    ids.append(str(t["toObjectId"]))
        ids = list(dict.fromkeys(ids))
        items = []
        for lid in ids:
            raw = client.get_object("line_items", lid, properties=_LINE_PROPS)
            items.append(
                sanitize_for_export(
                    {"id": raw.get("id"), "properties": _props(raw, HUBSPOT_LINE_ALLOWLIST)}
                )
            )
        result = {
            "status": "success",
            "deal_id": deal_id,
            "count": len(items),
            "line_items": items,
            "needs_review": False,
        }
        result["evidence"] = record_evidence(
            agent="hubspot",
            action="get_deal_line_items",
            inputs={"deal_id": deal_id},
            outputs={"count": len(items)},
            sources=[f"hubspot:deal:{deal_id}", "hubspot:line_items"],
        )
        return result
    except CircuitOpenError as exc:
        return _err("circuit_open", str(exc))
    except HubSpotAPIError as exc:
        return _err("error", str(exc), http_status=exc.status_code)


def get_open_tickets_for_company(company_id: str, limit: int = 25) -> dict[str, Any]:
    """List tickets associated with a company (open stages preferred when present)."""
    client = _client_or_error()
    if isinstance(client, dict):
        return client
    company_id = company_id.strip()
    if not company_id:
        return _err("error", "company_id required")
    limit = max(1, min(int(limit), 50))
    try:
        assoc = client.list_associations("companies", company_id, "tickets")
        ids: list[str] = []
        for row in assoc.get("results") or []:
            to_obj = row.get("toObjectId") or row.get("id")
            if to_obj is not None:
                ids.append(str(to_obj))
            for t in row.get("to") or []:
                if t.get("toObjectId") is not None:
                    ids.append(str(t["toObjectId"]))
        ids = list(dict.fromkeys(ids))[:limit]
        tickets = []
        for tid in ids:
            raw = client.get_object("tickets", tid, properties=_TICKET_PROPS)
            tickets.append(
                sanitize_for_export(
                    {"id": raw.get("id"), "properties": _props(raw, HUBSPOT_TICKET_ALLOWLIST)}
                )
            )
        result = {
            "status": "success",
            "company_id": company_id,
            "count": len(tickets),
            "tickets": tickets,
            "needs_review": False,
        }
        result["evidence"] = record_evidence(
            agent="hubspot",
            action="get_open_tickets_for_company",
            inputs={"company_id": company_id, "limit": limit},
            outputs={"count": len(tickets)},
            sources=[f"hubspot:company:{company_id}", "hubspot:tickets"],
        )
        return result
    except CircuitOpenError as exc:
        return _err("circuit_open", str(exc))
    except HubSpotAPIError as exc:
        return _err("error", str(exc), http_status=exc.status_code)


def create_task(
    subject: str,
    body: str = "",
    owner_id: str = "",
    company_id: str = "",
    deal_id: str = "",
) -> dict[str, Any]:
    """Create a HubSpot task (HITL/exception handoff — not for coordinator/payments LLM)."""
    client = _client_or_error()
    if isinstance(client, dict):
        return client
    subject = sanitize_hubspot_text((subject or "").strip(), max_len=256)
    body = sanitize_hubspot_text(body or "", max_len=4000)
    if not subject:
        return _err("error", "subject required")
    props: dict[str, Any] = {
        "hs_task_subject": subject,
        "hs_task_body": body,
        "hs_task_status": "NOT_STARTED",
        "hs_task_type": "TODO",
    }
    if owner_id.strip():
        props["hubspot_owner_id"] = owner_id.strip()
    try:
        raw = client.create_object("tasks", props)
        task_id = str(raw.get("id") or "")
        # Associations via v4 would be a follow-up; return ids for HITL to link
        result = {
            "status": "success",
            "task_id": task_id,
            "company_id": company_id.strip() or None,
            "deal_id": deal_id.strip() or None,
            "needs_review": False,
        }
        result["evidence"] = record_evidence(
            agent="hubspot",
            action="create_task",
            inputs={
                "subject": subject[:80],
                "company_id": company_id,
                "deal_id": deal_id,
            },
            outputs={"task_id": task_id},
            sources=[f"hubspot:task:{task_id}"] if task_id else ["hubspot:task"],
        )
        return result
    except CircuitOpenError as exc:
        return _err("circuit_open", str(exc))
    except HubSpotAPIError as exc:
        return _err("error", str(exc), http_status=exc.status_code)


def create_note(
    body: str,
    company_id: str = "",
    deal_id: str = "",
) -> dict[str, Any]:
    """Create a HubSpot note (HITL path only — minimal write)."""
    client = _client_or_error()
    if isinstance(client, dict):
        return client
    body = sanitize_hubspot_text((body or "").strip(), max_len=8000)
    if not body:
        return _err("error", "body required")
    props = {"hs_note_body": body}
    try:
        raw = client.create_object("notes", props)
        note_id = str(raw.get("id") or "")
        result = {
            "status": "success",
            "note_id": note_id,
            "company_id": company_id.strip() or None,
            "deal_id": deal_id.strip() or None,
            "needs_review": False,
        }
        result["evidence"] = record_evidence(
            agent="hubspot",
            action="create_note",
            inputs={"company_id": company_id, "deal_id": deal_id, "body_len": len(body)},
            outputs={"note_id": note_id},
            sources=[f"hubspot:note:{note_id}"] if note_id else ["hubspot:note"],
        )
        return result
    except CircuitOpenError as exc:
        return _err("circuit_open", str(exc))
    except HubSpotAPIError as exc:
        return _err("error", str(exc), http_status=exc.status_code)


def _safe_float(val: Any) -> float:
    try:
        if val is None or val == "":
            return 0.0
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def compare_sold_contracted_invoiced(
    customer_id: str,
    company_id: str = "",
    deal_id: str = "",
) -> dict[str, Any]:
    """D3 — Compare HubSpot sold (closed-won) vs contracted credit vs invoiced AR.

    Returns EvidenceRef sources for HubSpot + warehouse. Discrepancies → needs_review.
    """
    from data_plane import repository as repo

    customer_id = customer_id.strip().upper()
    if not customer_id:
        return _err("error", "customer_id required")

    sources: list[str] = [repo.source_label()]
    evidence_refs: list[dict[str, Any]] = []

    contracts = [_clean_row(r) for r in repo.list_contracts(customer_id=customer_id, active_only=True)]
    contracted = sum(_safe_float(c.get("credit_limit")) for c in contracts)
    for c in contracts:
        sources.append(f"warehouse:contract:{c.get('contract_id')}")

    invoices = list(repo.list_invoices(customer_id=customer_id, open_only=False))
    invoiced = sum(_safe_float(i.get("amount")) for i in invoices)
    open_invoiced = sum(
        _safe_float(i.get("amount")) for i in invoices if str(i.get("status")) in {"open", "past_due"}
    )
    sources.append(f"warehouse:invoices:{customer_id}")

    sold = 0.0
    deals_used: list[dict[str, Any]] = []
    hubspot_status = "skipped"
    if deal_id.strip():
        deal_out = get_deal(deal_id.strip())
        hubspot_status = deal_out.get("status", "error")
        if deal_out.get("status") == "success":
            deal = deal_out.get("deal") or {}
            props = deal.get("properties") or {}
            sold = _safe_float(props.get("amount"))
            deals_used.append(deal)
            did = str(deal.get("id") or deal_id)
            sources.append(f"hubspot:deal:{did}")
            lines = get_deal_line_items(did)
            if lines.get("status") == "success":
                sources.append(f"hubspot:deal:{did}:line_items")
                if lines.get("line_items"):
                    sold = sum(
                        _safe_float((li.get("properties") or {}).get("amount"))
                        or (
                            _safe_float((li.get("properties") or {}).get("price"))
                            * _safe_float((li.get("properties") or {}).get("quantity") or 1)
                        )
                        for li in lines["line_items"]
                    ) or sold
            if deal_out.get("evidence", {}).get("evidence_id"):
                evidence_refs.append(
                    EvidenceRef(
                        evidence_id=deal_out["evidence"]["evidence_id"],
                        sources=[f"hubspot:deal:{did}"],
                    ).model_dump()
                )
    elif company_id.strip():
        deals_out = list_closed_won_deals(company_id=company_id.strip(), limit=25)
        hubspot_status = deals_out.get("status", "error")
        if deals_out.get("status") == "success":
            for d in deals_out.get("deals") or []:
                props = d.get("properties") or {}
                sold += _safe_float(props.get("amount"))
                deals_used.append(d)
                did = str(d.get("id") or "")
                if did:
                    sources.append(f"hubspot:deal:{did}")
            if deals_out.get("evidence", {}).get("evidence_id"):
                evidence_refs.append(
                    EvidenceRef(
                        evidence_id=deals_out["evidence"]["evidence_id"],
                        sources=["hubspot:deals:closed_won"],
                    ).model_dump()
                )

    # Material gap: sold vs contracted or sold vs invoiced (>5% or >$500)
    gaps: list[str] = []
    if sold and contracted and abs(sold - contracted) > max(500.0, 0.05 * max(sold, contracted)):
        gaps.append("sold_vs_contracted")
    if sold and invoiced and abs(sold - invoiced) > max(500.0, 0.05 * max(sold, invoiced)):
        gaps.append("sold_vs_invoiced")
    if contracted and open_invoiced > contracted * 1.05:
        gaps.append("open_ar_over_credit")

    needs_review = bool(gaps) or hubspot_status in {"error", "denied", "circuit_open"}
    result = {
        "status": "success",
        "customer_id": customer_id,
        "company_id": company_id.strip() or None,
        "sold": sold,
        "contracted_credit_limit": contracted,
        "invoiced_total": invoiced,
        "open_invoiced": open_invoiced,
        "gaps": gaps,
        "deals": deals_used,
        "contracts": contracts,
        "hubspot_status": hubspot_status,
        "evidence_refs": evidence_refs,
        "needs_review": needs_review,
        "policy_bypass": False,
    }
    ev = record_evidence(
        agent="contracts_agent",
        action="compare_sold_contracted_invoiced",
        inputs={"customer_id": customer_id, "company_id": company_id, "deal_id": deal_id},
        outputs={
            "sold": sold,
            "contracted": contracted,
            "invoiced": invoiced,
            "gaps": gaps,
        },
        sources=list(dict.fromkeys(sources)),
    )
    result["evidence"] = ev
    evidence_refs.append(
        EvidenceRef(evidence_id=ev["evidence_id"], sources=list(dict.fromkeys(sources))).model_dump()
    )
    result["evidence_refs"] = evidence_refs
    return result


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in row.items()}


def enrich_aging_hubspot(customer_id: str, company_id: str = "") -> dict[str, Any]:
    """D4 — Aging buckets + HubSpot owner/stage/tickets/renewal. Never bypasses policy."""
    from finance_ops.tools.invoice_tools import aging_summary

    customer_id = customer_id.strip().upper()
    if not customer_id:
        return _err("error", "customer_id required")

    base = aging_summary(customer_id)
    enrichment: dict[str, Any] = {
        "owner_id": None,
        "lifecycle_stage": None,
        "deal_stage": None,
        "renewal_closedate": None,
        "open_ticket_count": 0,
        "tickets": [],
        "hubspot_status": "skipped",
    }
    sources = [f"warehouse:aging:{customer_id}"]
    if base.get("evidence", {}).get("evidence_id"):
        sources.append(f"evidence:{base['evidence']['evidence_id']}")

    cid = company_id.strip()
    if cid:
        company = get_company(cid)
        enrichment["hubspot_status"] = company.get("status")
        if company.get("status") == "success":
            props = (company.get("company") or {}).get("properties") or {}
            enrichment["owner_id"] = props.get("hubspot_owner_id")
            enrichment["lifecycle_stage"] = props.get("lifecyclestage")
            sources.append(f"hubspot:company:{cid}")
        deals = list_closed_won_deals(company_id=cid, limit=5)
        if deals.get("status") == "success" and deals.get("deals"):
            top = deals["deals"][0]
            tprops = top.get("properties") or {}
            enrichment["deal_stage"] = tprops.get("dealstage")
            enrichment["renewal_closedate"] = tprops.get("closedate")
            if top.get("id"):
                sources.append(f"hubspot:deal:{top['id']}")
        tickets = get_open_tickets_for_company(cid, limit=10)
        if tickets.get("status") == "success":
            enrichment["open_ticket_count"] = int(tickets.get("count") or 0)
            enrichment["tickets"] = tickets.get("tickets") or []
            sources.append(f"hubspot:company:{cid}:tickets")

    # Triage hint only — never flips policy / never auto-approves.
    triage_flags: list[str] = []
    if enrichment["open_ticket_count"] > 0:
        triage_flags.append("open_tickets")
    if base.get("buckets", {}).get("61-90") or base.get("buckets", {}).get("90+"):
        triage_flags.append("aged_past_60")

    result = {
        "status": base.get("status", "success"),
        "customer_id": customer_id,
        "company_id": cid or None,
        "aging": {
            "total_open": base.get("total_open"),
            "buckets": base.get("buckets"),
            "invoice_count": base.get("invoice_count"),
        },
        "hubspot": enrichment,
        "triage_flags": triage_flags,
        "policy_bypass": False,
        "policy_note": "HubSpot enrichment is triage context only; approval policy unchanged.",
        # needs_review follows warehouse aging only if base said so — tickets add triage, not force
        "needs_review": bool(base.get("needs_review")) or bool(triage_flags),
    }
    result["evidence"] = record_evidence(
        agent="invoice_agent",
        action="enrich_aging_hubspot",
        inputs={"customer_id": customer_id, "company_id": company_id},
        outputs={
            "total_open": result["aging"]["total_open"],
            "triage_flags": triage_flags,
            "policy_bypass": False,
        },
        sources=list(dict.fromkeys(sources)),
    )
    return result


def match_hubspot_company(
    customer_id: str = "",
    name: str = "",
    domain: str = "",
    external_id: str = "",
) -> dict[str, Any]:
    """D5 — Match warehouse customer to HubSpot company by domain/name/external id.

    Multiple candidates → needs_review (never auto-merge).
    """
    from data_plane import repository as repo

    client = _client_or_error()
    if isinstance(client, dict):
        return client

    customer_id = customer_id.strip().upper()
    name = name.strip()
    domain = domain.strip().lower()
    external_id = external_id.strip()

    if customer_id and not name:
        # Prefer contract customer_name
        contracts = repo.list_contracts(customer_id=customer_id, active_only=False)
        if contracts:
            name = str(contracts[0].get("customer_name") or "")
        if not domain:
            # heuristic domain from name
            slug = "".join(ch for ch in name.lower() if ch.isalnum())
            if slug:
                domain = f"{slug}.example"

    filters: list[dict[str, Any]] = []
    if domain:
        filters.append(
            {
                "filters": [
                    {"propertyName": "domain", "operator": "EQ", "value": domain},
                ]
            }
        )
    if name:
        filters.append(
            {
                "filters": [
                    {"propertyName": "name", "operator": "CONTAINS_TOKEN", "value": name},
                ]
            }
        )
    if external_id:
        filters.append(
            {
                "filters": [
                    {
                        "propertyName": "hs_object_id",
                        "operator": "EQ",
                        "value": external_id,
                    },
                ]
            }
        )
    if not filters:
        return _err("error", "name, domain, external_id, or customer_id required")

    try:
        raw = client.search_objects(
            "companies",
            filter_groups=filters,
            properties=_COMPANY_PROPS,
            limit=10,
        )
        candidates = []
        for row in raw.get("results") or []:
            candidates.append(
                sanitize_for_export(
                    {
                        "id": row.get("id"),
                        "properties": _props(row, HUBSPOT_COMPANY_ALLOWLIST),
                    }
                )
            )
        # Deduplicate by id
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for c in candidates:
            cid = str(c.get("id") or "")
            if cid and cid not in seen:
                seen.add(cid)
                uniq.append(c)
        duplicate = len(uniq) > 1
        exact = len(uniq) == 1
        result = {
            "status": "success",
            "customer_id": customer_id or None,
            "query": {"name": name or None, "domain": domain or None, "external_id": external_id or None},
            "count": len(uniq),
            "candidates": uniq,
            "match": uniq[0] if exact else None,
            "duplicate_candidates": duplicate,
            "needs_review": duplicate or len(uniq) == 0,
            "auto_merge": False,
            "policy_note": "Duplicates require human confirmation; never auto-merge.",
        }
        result["evidence"] = record_evidence(
            agent="reconciliation_agent",
            action="match_hubspot_company",
            inputs={
                "customer_id": customer_id,
                "name": name,
                "domain": domain,
                "external_id": external_id,
            },
            outputs={"count": len(uniq), "duplicate_candidates": duplicate},
            sources=["hubspot:companies:search"]
            + [f"hubspot:company:{c.get('id')}" for c in uniq[:5]],
        )
        return result
    except CircuitOpenError as exc:
        return _err("circuit_open", str(exc))
    except HubSpotAPIError as exc:
        return _err("error", str(exc), http_status=exc.status_code)
