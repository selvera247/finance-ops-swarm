"""C5 — sanitize payloads before evidence, Slack, MCP, and logs.

Redacts secrets and obvious credential-shaped strings. Keeps business ids
(INV-*, PAY-*, CUST-*, C-*) intact. D8 also masks email/phone and HubSpot
free-text injection markers for audit/logs.
"""

from __future__ import annotations

import re
from typing import Any

_REDACT = "[REDACTED]"
_EMAIL_MASK = "[EMAIL]"
_PHONE_MASK = "[PHONE]"

# Env-style and bearer secrets
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|authorization|webhook|"
    r"private[_-]?key|access[_-]?key|refresh[_-]?token|client[_-]?secret|"
    r"slack_|google_|gemini_|aws_|bearer|hubspot_)",
    re.I,
)

# Long token-like literals (PATs, JWTs, slack tokens, hex secrets)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b("
    r"github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|Bearer\s+[A-Za-z0-9._\-+/=]{20,}"
    r"|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9._-]{10,}"
    r"|AIza[0-9A-Za-z_-]{20,}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|pat-[A-Za-z0-9\-]{20,}"
    r"|hooks\.slack\.com/services/[A-Za-z0-9/]+"
    r")"
)

# Optional account-ish digit runs (keep short refs; redact long digit strings)
_ACCOUNT_RE = re.compile(r"\b\d{12,19}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{3}\)?[\s\-.]?)\d{3}[\s\-.]?\d{4}(?!\w)"
)

# Prompt-injection / instruction-override markers in HubSpot notes/tasks
_INJECTION_RE = re.compile(
    r"(?is)("
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?"
    r"|system\s*:\s*"
    r"|<\s*/?\s*system\s*>"
    r"|you\s+are\s+now\s+"
    r"|do\s+not\s+follow\s+policy"
    r")"
)

# HubSpot property allowlists (D8) — only these keys leave the CRM boundary.
HUBSPOT_COMPANY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "name",
        "domain",
        "hs_object_id",
        "hubspot_owner_id",
        "lifecyclestage",
        "hs_lastmodifieddate",
    }
)
HUBSPOT_DEAL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "dealname",
        "amount",
        "dealstage",
        "pipeline",
        "closedate",
        "hs_object_id",
        "hubspot_owner_id",
        "hs_is_closed_won",
    }
)
HUBSPOT_LINE_ALLOWLIST: frozenset[str] = frozenset(
    {"name", "quantity", "price", "amount", "hs_sku", "hs_product_id"}
)
HUBSPOT_TICKET_ALLOWLIST: frozenset[str] = frozenset(
    {"subject", "hs_pipeline_stage", "hs_ticket_priority", "createdate", "hs_object_id"}
)


def mask_email_phone(text: str) -> str:
    if not text:
        return text
    out = _EMAIL_RE.sub(_EMAIL_MASK, text)
    out = _PHONE_RE.sub(_PHONE_MASK, out)
    return out


def sanitize_hubspot_text(text: str, *, max_len: int = 4000) -> str:
    """Sanitize HubSpot free text (notes/tasks) for writes and audit."""
    if not text:
        return text
    out = sanitize_string(text, redact_accounts=True, mask_pii=True)
    out = _INJECTION_RE.sub("[INJECTION_REMOVED]", out)
    return out[:max_len]


def allowlist_props(props: dict[str, Any] | None, allow: frozenset[str]) -> dict[str, Any]:
    raw = props if isinstance(props, dict) else {}
    return {k: v for k, v in raw.items() if k in allow and v is not None}


def sanitize_string(
    text: str,
    *,
    redact_accounts: bool = True,
    mask_pii: bool = True,
) -> str:
    if not text:
        return text
    out = _SECRET_VALUE_RE.sub(_REDACT, text)
    if mask_pii:
        out = mask_email_phone(out)
    if redact_accounts:
        out = _ACCOUNT_RE.sub(_REDACT, out)
    return out


def sanitize_for_export(
    value: Any,
    *,
    redact_accounts: bool = True,
    mask_pii: bool = True,
    _depth: int = 0,
) -> Any:
    """Deep-sanitize dict/list/str for export surfaces."""
    if _depth > 12:
        return _REDACT
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_string(value, redact_accounts=redact_accounts, mask_pii=mask_pii)
    if isinstance(value, bytes):
        return _REDACT
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            key_str = str(k)
            if _SECRET_KEY_RE.search(key_str):
                out[k] = _REDACT
            elif key_str.lower() in {"email", "phone", "mobilephone", "hs_email", "hs_phone"}:
                out[k] = _EMAIL_MASK if "mail" in key_str.lower() else _PHONE_MASK
            else:
                out[k] = sanitize_for_export(
                    v, redact_accounts=redact_accounts, mask_pii=mask_pii, _depth=_depth + 1
                )
        return out
    if isinstance(value, (list, tuple)):
        return [
            sanitize_for_export(
                v, redact_accounts=redact_accounts, mask_pii=mask_pii, _depth=_depth + 1
            )
            for v in value
        ]
    return sanitize_string(str(value), redact_accounts=redact_accounts, mask_pii=mask_pii)
