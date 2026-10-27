"""#8 Slack HITL — notify + interactive resume (webhook / slash stand-in).

Env:
  SLACK_WEBHOOK_URL     Incoming webhook for approval cards (optional)
  SLACK_BOT_TOKEN       xoxb-… for chat.postMessage (optional alternative)
  SLACK_HITL_CHANNEL    Channel id when using bot token
  HITL_PUBLIC_BASE_URL  Base URL for Approve/Reject links (default http://127.0.0.1:8787)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from finance_ops.runtime.hitl import PendingApproval
from finance_ops.runtime.sanitize import sanitize_for_export, sanitize_string

_DOTENV_LOADED = False


def _ensure_dotenv() -> None:
    """Load finance_ops/.env and repo .env so CLI one-liners see Slack vars."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[2]
    for path in (root / "finance_ops" / ".env", root / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


def hitl_public_base() -> str:
    _ensure_dotenv()
    return os.getenv("HITL_PUBLIC_BASE_URL", "http://127.0.0.1:8787").rstrip("/")


def approval_links(approval: PendingApproval) -> dict[str, str]:
    base = hitl_public_base()
    return {
        "approve": (
            f"{base}/approve?id={approval.approval_id}&token={approval.resume_token}"
        ),
        "reject": (
            f"{base}/reject?id={approval.approval_id}&token={approval.resume_token}"
        ),
        "list": f"{base}/approvals",
    }


def slack_message_blocks(approval: PendingApproval) -> list[dict[str, Any]]:
    links = approval_links(approval)
    summary = sanitize_string(approval.summary or "", redact_accounts=True)
    return sanitize_for_export(
        [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"HITL: {approval.kind}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{summary}*\n"
                        f"Amount: `${approval.amount:,.2f} {approval.currency}`\n"
                        f"Id: `{approval.approval_id}` · status: `{approval.status}`"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "url": links["approve"],
                        "action_id": "hitl_approve",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "url": links["reject"],
                        "action_id": "hitl_reject",
                    },
                ],
            },
        ],
        redact_accounts=True,
    )


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return {"ok": True, "status": resp.status}
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"ok": True, "raw": body, "status": resp.status}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {exc.code}", "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def notify_slack(approval: PendingApproval) -> dict[str, Any]:
    """Post approval card to Slack if webhook or bot token configured."""
    _ensure_dotenv()
    webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    bot = os.getenv("SLACK_BOT_TOKEN", "").strip()
    channel = os.getenv("SLACK_HITL_CHANNEL", "").strip()
    links = approval_links(approval)
    text = sanitize_string(
        f"HITL approval needed: {approval.summary} "
        f"(${approval.amount:,.2f}) — {approval.approval_id}",
        redact_accounts=True,
    )
    blocks = slack_message_blocks(approval)

    if webhook:
        result = _post_json(
            webhook,
            {"text": text, "blocks": blocks},
        )
        return {
            "channel": "webhook",
            "sent": bool(result.get("ok", True) and "error" not in result),
            "result": result,
            "links": links,
        }

    if bot and channel:
        result = _post_json(
            "https://slack.com/api/chat.postMessage",
            {"channel": channel, "text": text, "blocks": blocks},
            headers={"Authorization": f"Bearer {bot}"},
        )
        return {
            "channel": "bot",
            "sent": bool(result.get("ok")),
            "result": result,
            "links": links,
        }

    return {
        "channel": "none",
        "sent": False,
        "hint": "Set SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN+SLACK_HITL_CHANNEL",
        "links": links,
    }


def parse_slack_interaction_payload(form_payload: str) -> dict[str, Any]:
    """Parse Slack interactive payload JSON (url-encoded `payload=` body already decoded)."""
    data = json.loads(form_payload)
    actions = data.get("actions") or []
    action = actions[0] if actions else {}
    action_id = action.get("action_id") or ""
    # Prefer button URL query (link buttons) — interactive value fallback:
    value = action.get("value") or ""
    decision = None
    if "approve" in action_id.lower() or value == "approved":
        decision = "approved"
    elif "reject" in action_id.lower() or value == "rejected":
        decision = "rejected"
    return {
        "decision": decision,
        "user": (data.get("user") or {}).get("username") or (data.get("user") or {}).get("id"),
        "raw_action": action_id,
        "message_ts": (data.get("message") or {}).get("ts"),
    }
