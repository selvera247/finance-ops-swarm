#!/usr/bin/env python3
"""Offline eval helpers that do not require an LLM key.

Validates tool-level behavior for portfolio AgentOps demos. Extend later with
live `adk` trajectory evaluation against cases.yaml prompts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finance_ops.tools.invoice_tools import aging_summary  # noqa: E402
from finance_ops.tools.payment_tools import suggest_payment_match  # noqa: E402
from finance_ops.tools.contract_tools import lookup_customer_contract  # noqa: E402
from finance_ops.tools.graph_tools import graph_neighborhood  # noqa: E402
from finance_ops.tools.rag_tools import search_policies  # noqa: E402


def _check(name: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    return condition


def main() -> int:
    cases_path = Path(__file__).with_name("cases.yaml")
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8"))["cases"]
    print(f"Loaded {len(cases)} prompt cases from {cases_path.name}")
    print("Running tool-level smoke checks...\n")

    ok = True
    aging = aging_summary("CUST-ACME")
    ok &= _check(
        "aging-acme",
        aging["status"] == "success" and aging["invoice_count"] >= 2,
        f"total_open={aging.get('total_open')}",
    )

    match = suggest_payment_match("PAY-9002")
    ok &= _check(
        "unmatched-payment",
        match.get("recommendation") is not None and match.get("needs_review") is True,
        f"recommendation={match.get('recommendation')}",
    )

    contract = lookup_customer_contract("CUST-NORTH")
    terms = (contract.get("contracts") or [{}])[0].get("payment_terms")
    ok &= _check("contract-terms", terms == "Net 45", f"terms={terms}")

    neighborhood = graph_neighborhood("PAY-9002", max_hops=2)
    ok &= _check(
        "graph-walk",
        neighborhood["status"] == "success" and neighborhood["nodes_reached"] > 1,
        f"nodes_reached={neighborhood.get('nodes_reached')}",
    )

    policies = search_policies("write off unmatched payment approval")
    ok &= _check(
        "governance-policy-rag",
        len(policies.get("hits", [])) > 0,
        f"hits={[h['doc_id'] for h in policies.get('hits', [])]}",
    )

    from finance_ops.governance.rbac import is_tool_allowed

    for tool in ("apply_payment_match", "decide_approval", "request_approval"):
        allowed, reason = is_tool_allowed("finance_ops_coordinator", tool)
        ok &= _check(
            f"rbac-deny-{tool}",
            allowed is False,
            reason,
        )

    print("\nNext: run live prompts with `adk run finance_ops` using evals/cases.yaml")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
