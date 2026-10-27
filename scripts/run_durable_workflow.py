#!/usr/bin/env python3
"""Run or resume the durable portal extract → reconcile DAG (#1)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", default=None, help="Existing WF- run_id")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Disable Playwright fallback on resolve miss",
    )
    args = parser.parse_args()

    from finance_ops.runtime.durable import DurableWorkflow, portal_reconcile_handlers

    wf = DurableWorkflow()
    handlers = portal_reconcile_handlers()
    if args.resume:
        state = wf.resume(args.resume, handlers, max_retries=3)
    else:
        state = wf.create(
            list(handlers.keys()),
            meta={"allow_browser": not args.no_browser},
        )
        state = wf.run(handlers, state=state, max_retries=3)

    print(json.dumps(state.model_dump(), indent=2, default=str))
    return 0 if state.status.value == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
