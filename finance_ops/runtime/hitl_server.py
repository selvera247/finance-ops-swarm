"""HITL gate — local UI + API + Slack interactive resume (#8)."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote_plus, urlparse

from finance_ops.runtime.hitl import DEFAULT_STORE


HTML = """<!doctype html>
<html><head><title>HITL Approvals</title></head>
<body style="font-family:sans-serif;max-width:800px;margin:2rem auto">
<h1>HITL Approval Gate</h1>
<p>Local UI + Slack link-button target (Slack/Teams stand-in).</p>
{body}
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        pass

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/approvals"}:
            rows = DEFAULT_STORE.list("pending")
            if not rows:
                body = "<p>No pending approvals.</p>"
            else:
                parts = ["<ul>"]
                for r in rows:
                    parts.append(
                        "<li>"
                        f"<strong>{r.approval_id}</strong> — {r.summary} "
                        f"(${r.amount:,.2f} {r.currency}) "
                        f"<a href='/approve?id={r.approval_id}&token={r.resume_token}'>Approve</a> | "
                        f"<a href='/reject?id={r.approval_id}&token={r.resume_token}'>Reject</a>"
                        "</li>"
                    )
                parts.append("</ul>")
                body = "".join(parts)
            self._html(HTML.format(body=body))
            return
        if parsed.path in {"/approve", "/reject"}:
            qs = parse_qs(parsed.query)
            approval_id = (qs.get("id") or [""])[0]
            token = (qs.get("token") or [""])[0]
            decision = "approved" if parsed.path == "/approve" else "rejected"
            actor = (qs.get("actor") or ["hitl_web"])[0]
            try:
                from finance_ops.runtime.hitl_effects import after_decision

                item = DEFAULT_STORE.decide(
                    approval_id, decision=decision, actor=actor, resume_token=token
                )
                effect = after_decision(item)
                effect_line = (
                    f"<p>effect: applied={effect.get('applied')} "
                    f"{effect.get('payment_id') or ''}→{effect.get('invoice_id') or ''}</p>"
                    if effect.get("kind") or effect.get("applied")
                    else ""
                )
                self._html(
                    HTML.format(
                        body=(
                            f"<p>{decision}: {item.approval_id}</p>"
                            f"<p>decided_by={item.decided_by}</p>"
                            f"{effect_line}"
                            f"<p><a href='/'>Back</a></p>"
                        )
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self._html(HTML.format(body=f"<p>Error: {exc}</p>"), code=400)
            return
        if parsed.path.startswith("/api/approval/"):
            approval_id = parsed.path.rsplit("/", 1)[-1]
            item = DEFAULT_STORE.get(approval_id)
            if item is None:
                self._json({"error": "not_found"}, code=404)
                return
            self._json(item.model_dump())
            return
        if parsed.path == "/health":
            self._json({"status": "ok", "slack": True})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        # Slack interactive / slash: application/x-www-form-urlencoded payload=...
        if parsed.path in {"/slack/interactions", "/slack/commands"}:
            form = parse_qs(raw.decode("utf-8"))
            if "payload" in form:
                payload_raw = unquote_plus(form["payload"][0])
                from finance_ops.runtime.slack_hitl import parse_slack_interaction_payload

                parsed_action = parse_slack_interaction_payload(payload_raw)
                # Link buttons open /approve|/reject in browser — interactions
                # with value=approval_id:token:decision are also supported.
                value = ((json.loads(payload_raw).get("actions") or [{}])[0]).get("value") or ""
                if ":" in value:
                    approval_id, token, decision = (value.split(":", 2) + ["", "", ""])[:3]
                    try:
                        from finance_ops.runtime.hitl_effects import after_decision

                        item = DEFAULT_STORE.decide(
                            approval_id,
                            decision=decision,  # type: ignore[arg-type]
                            actor=f"slack:{parsed_action.get('user') or 'user'}",
                            resume_token=token,
                        )
                        effect = after_decision(item)
                        self._json(
                            {
                                "ok": True,
                                "approval": item.model_dump(),
                                "effect": effect,
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        self._json({"ok": False, "error": str(exc)}, code=400)
                    return
                self._json(
                    {
                        "ok": True,
                        "hint": "Use link buttons (open Approve URL) or value=id:token:decision",
                        "parsed": parsed_action,
                    }
                )
                return
            self._json({"ok": True, "hint": "no payload"})
            return

        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, code=400)
            return
        if parsed.path == "/api/decide":
            try:
                from finance_ops.runtime.hitl_effects import after_decision

                item = DEFAULT_STORE.decide(
                    body["approval_id"],
                    decision=body["decision"],
                    actor=body.get("actor", "api"),
                    resume_token=body.get("resume_token"),
                )
                effect = after_decision(item)
                payload = item.model_dump()
                payload["effect"] = effect
                self._json(payload)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, code=400)
            return
        if parsed.path == "/api/notify":
            # Re-notify Slack for an existing approval
            from finance_ops.runtime.slack_hitl import notify_slack

            item = DEFAULT_STORE.get(body.get("approval_id", ""))
            if item is None:
                self._json({"error": "not_found"}, code=404)
                return
            self._json(notify_slack(item))
            return
        self.send_error(404)

    def _html(self, content: str, code: int = 200) -> None:
        data = content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: dict, code: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"HITL gate at http://{args.host}:{args.port}/")
    print("  Slack interactions: POST /slack/interactions")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
