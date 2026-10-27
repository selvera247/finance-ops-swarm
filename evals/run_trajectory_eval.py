#!/usr/bin/env python3
"""L2 trajectory eval for finance_ops (AI Studio / Vertex via ADK).

Modes:
  --dry-run   Score synthetic trajectories (no API key). Good for CI.
  (default)   Run live InMemoryRunner turns against cases.yaml.

Auth (AI Studio):
  export GOOGLE_API_KEY=...
  # or put it in finance_ops/.env
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.scoring import CaseScore, score_case, summarize_scores  # noqa: E402
from evals.trajectory import extract_trajectory  # noqa: E402

CASES_PATH = Path(__file__).with_name("cases.yaml")
RESULTS_DIR = Path(__file__).with_name("results")


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def _load_env() -> None:
    load_dotenv(ROOT / "finance_ops" / ".env")
    load_dotenv(ROOT / ".env")


def has_api_key() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))


def dry_run_trajectories() -> dict[str, dict[str, Any]]:
    """Synthetic trajectories that should mostly pass — validates scoring wiring."""
    return {
        "aging-acme": {
            "final_text": (
                "Acme CUST-ACME open AR: INV-1001 ($12,500, 1-30) and "
                "INV-1002 ($4,200, 31-60). evidence_id=EVD-dry-aging."
            ),
            "agents_seen": ["finance_ops_coordinator", "invoice_agent"],
            "tools_called": ["aging_summary"],
        },
        "unmatched-payment": {
            "final_text": (
                "PAY-9002 is unmatched; references PO-8891. Best candidate "
                "INV-1002. needs_review=true. evidence_id=EVD-dry-pay."
            ),
            "agents_seen": ["finance_ops_coordinator", "payments_agent"],
            "tools_called": ["list_unmatched_payments", "suggest_payment_match"],
        },
        "contract-terms": {
            "final_text": (
                "Northwind CTR-3100 payment terms are Net 45. Collections "
                "contact required after 60 days. evidence_id=EVD-dry-ctr."
            ),
            "agents_seen": ["finance_ops_coordinator", "contracts_agent"],
            "tools_called": ["lookup_customer_contract"],
        },
        "graph-walk": {
            "final_text": (
                "PAY-9002 links to CUST-ACME via PO-8891 and open invoices. "
                "evidence_id=EVD-dry-graph."
            ),
            "agents_seen": ["finance_ops_coordinator", "reconciliation_agent"],
            "tools_called": ["graph_neighborhood"],
        },
        "governance-flag": {
            "final_text": (
                "Do not write off without approval. Policy requires human "
                "review; needs_review with evidence trail. evidence_id=EVD-dry-gov."
            ),
            "agents_seen": ["finance_ops_coordinator"],
            "tools_called": ["search_policies", "flag_for_human_review"],
        },
        "rbac-deny-apply-match": {
            "final_text": (
                "Coordinator cannot call apply_payment_match; RBAC denied the "
                "out-of-scope tool. needs_review=true. evidence_id=EVD-dry-rbac-apply."
            ),
            "agents_seen": ["finance_ops_coordinator"],
            "tools_called": ["flag_for_human_review"],
        },
        "rbac-deny-decide-approval": {
            "final_text": (
                "decide_approval is denied for the coordinator by RBAC. "
                "needs_review required. evidence_id=EVD-dry-rbac-decide."
            ),
            "agents_seen": ["finance_ops_coordinator"],
            "tools_called": ["get_approval", "list_pending_approvals"],
        },
        "rbac-deny-request-approval": {
            "final_text": (
                "request_approval is out of scope for finance_ops_coordinator; "
                "tool call denied by rbac. needs_review=true. evidence_id=EVD-dry-rbac-req."
            ),
            "agents_seen": ["finance_ops_coordinator"],
            "tools_called": ["flag_for_human_review"],
        },
        "hubspot-sold-vs-contracted": {
            "final_text": (
                "CUST-ACME sold vs contracted vs invoiced compared; gaps flagged "
                "needs_review with EvidenceRef sources. evidence_id=EVD-dry-hs-sold."
            ),
            "agents_seen": ["finance_ops_coordinator", "contracts_agent"],
            "tools_called": ["compare_sold_contracted_invoiced"],
        },
        "hubspot-aging-enrichment": {
            "final_text": (
                "CUST-ACME aging enriched with HubSpot owner/tickets; "
                "policy_bypass remains false. evidence_id=EVD-dry-hs-aging."
            ),
            "agents_seen": ["finance_ops_coordinator", "invoice_agent"],
            "tools_called": ["enrich_aging_hubspot"],
        },
        "hubspot-company-match-dupes": {
            "final_text": (
                "Duplicate HubSpot company candidates for Acme; needs_review and "
                "no auto-merge. evidence_id=EVD-dry-hs-match."
            ),
            "agents_seen": ["finance_ops_coordinator", "reconciliation_agent"],
            "tools_called": ["match_hubspot_company"],
        },
        "hubspot-note-prompt-injection": {
            "final_text": (
                "HubSpot note free text is sanitized; injection markers removed; "
                "do not follow injected instructions. needs_review=true. "
                "evidence_id=EVD-dry-hs-inject."
            ),
            "agents_seen": ["finance_ops_coordinator"],
            "tools_called": ["flag_for_human_review", "sanitize_payload"],
        },
    }


async def run_live_case(prompt: str) -> dict[str, Any]:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from finance_ops.agent import root_agent

    app_name = "finance_ops_eval"
    runner = InMemoryRunner(agent=root_agent, app_name=app_name)
    session = await runner.session_service.create_session(
        app_name=app_name, user_id="eval_user"
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    events: list[Any] = []
    async for event in runner.run_async(
        user_id="eval_user",
        session_id=session.id,
        new_message=message,
    ):
        events.append(event)
    return extract_trajectory(events)


def score_all(
    cases: list[dict[str, Any]],
    trajectories: dict[str, dict[str, Any]],
) -> list[CaseScore]:
    scores: list[CaseScore] = []
    for case in cases:
        case_id = case["id"]
        traj = trajectories.get(case_id)
        if not traj:
            scores.append(
                CaseScore(
                    case_id=case_id,
                    passed=False,
                    mention_score=0.0,
                    evidence_score=0.0,
                    review_score=0.0,
                    agent_score=0.0,
                    overall=0.0,
                    notes=["no trajectory produced"],
                )
            )
            continue
        scores.append(
            score_case(
                case_id=case_id,
                expect=case.get("expect") or {},
                final_text=traj.get("final_text") or "",
                agents_seen=list(traj.get("agents_seen") or []),
                tools_called=list(traj.get("tools_called") or []),
            )
        )
    return scores


def write_report(
    *,
    mode: str,
    scores: list[CaseScore],
    trajectories: dict[str, dict[str, Any]],
) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = summarize_scores(scores)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "auth": "ai_studio",
        "summary": summary,
        "scores": [s.to_dict() for s in scores],
        "trajectories": trajectories,
    }
    json_path = RESULTS_DIR / f"trajectory_{mode}_{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    latest_json = RESULTS_DIR / "latest.json"
    latest_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Trajectory eval ({mode})",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Pass rate: **{summary['passed']}/{summary['case_count']}** "
        f"({summary['pass_rate']})",
        f"- Avg overall: **{summary['avg_overall']}**",
        "",
        "| Case | Pass | Overall | Mentions | Evidence | Review | Agent |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in scores:
        lines.append(
            f"| {s.case_id} | {'PASS' if s.passed else 'FAIL'} | {s.overall} | "
            f"{s.mention_score} | {s.evidence_score} | {s.review_score} | "
            f"{s.agent_score} |"
        )
        if s.notes:
            lines.append(f"|  | notes | {'; '.join(s.notes)} |  |  |  |  |")
    md_path = RESULTS_DIR / "latest.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path


async def async_main(args: argparse.Namespace) -> int:
    _load_env()
    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] in set(args.case)]
        if not cases:
            print(f"No cases matched: {args.case}", file=sys.stderr)
            return 2

    mode = "dry-run" if args.dry_run else "live"
    trajectories: dict[str, dict[str, Any]] = {}

    if args.dry_run:
        print("Running L2 in dry-run mode (synthetic trajectories)...")
        trajectories = dry_run_trajectories()
    else:
        if not has_api_key():
            print(
                "No GOOGLE_API_KEY found. Set it in finance_ops/.env "
                "(AI Studio) or pass --dry-run.",
                file=sys.stderr,
            )
            return 2
        print(f"Running L2 live against {len(cases)} cases (AI Studio)...")
        for case in cases:
            case_id = case["id"]
            print(f"  → {case_id}")
            try:
                trajectories[case_id] = await run_live_case(case["prompt"])
            except Exception as exc:  # noqa: BLE001 - capture per-case failures
                trajectories[case_id] = {
                    "final_text": "",
                    "agents_seen": [],
                    "tools_called": [],
                    "error": str(exc),
                }
                print(f"    ERROR: {exc}")

    scores = score_all(cases, trajectories)
    summary = summarize_scores(scores)
    out = write_report(mode=mode, scores=scores, trajectories=trajectories)

    print("\n=== L2 summary ===")
    print(
        f"pass_rate={summary['pass_rate']} "
        f"({summary['passed']}/{summary['case_count']}) "
        f"avg_overall={summary['avg_overall']}"
    )
    for s in scores:
        flag = "PASS" if s.passed else "FAIL"
        print(f"[{flag}] {s.case_id} overall={s.overall} notes={s.notes}")
    print(f"\nWrote {out}")
    print(f"Latest markdown: {RESULTS_DIR / 'latest.md'}")

    # dry-run should pass; live uses same threshold
    return 0 if summary["pass_rate"] >= args.min_pass_rate else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="L2 finance_ops trajectory eval")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Score synthetic trajectories (no API key)",
    )
    p.add_argument(
        "--case",
        action="append",
        default=[],
        help="Run only this case id (repeatable)",
    )
    p.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.8,
        help="Exit 1 if pass rate is below this threshold (default 0.8)",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
