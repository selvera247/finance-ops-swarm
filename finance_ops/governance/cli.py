"""CLI for governance sweeps (Cloud Scheduler / cron).

Usage:
  PYTHONPATH=. python -m finance_ops.governance.cli sweep
  PYTHONPATH=. python -m finance_ops.governance.cli list
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finance ops governance CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sweep", help="Run agent lifecycle sweep (TTL + eval)")
    sub.add_parser("list", help="List registered agents")
    ship = sub.add_parser(
        "ship-audit",
        help="Backfill local audit.jsonl to BigQuery (requires FINANCE_OPS_AUDIT_BQ=true)",
    )
    ship.add_argument("--limit", type=int, default=None, help="Max JSONL lines to ship")

    args = parser.parse_args(argv)
    if args.cmd == "sweep":
        from finance_ops.governance.registry import sweep_lifecycle

        out = sweep_lifecycle()
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("status") == "success" else 1
    if args.cmd == "list":
        from finance_ops.governance.registry import list_agents

        print(json.dumps({"agents": list_agents()}, indent=2, default=str))
        return 0
    if args.cmd == "ship-audit":
        from finance_ops.governance.audit_bq import ship_audit_jsonl

        out = ship_audit_jsonl(limit=args.limit)
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("status") in {"success", "skipped"} else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
