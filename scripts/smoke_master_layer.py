#!/usr/bin/env python3
"""Smoke L7/L3/#8 artifacts without requiring GCP or Slack credentials."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    report: dict = {"checks": {}}

    one_pager = ROOT / "docs" / "cfo-cto-one-pager.md"
    report["checks"]["l7_one_pager"] = {
        "ok": one_pager.exists() and one_pager.stat().st_size > 500,
        "path": str(one_pager),
    }

    # L3: bigquery mode falls back cleanly
    os.environ["FINANCE_OPS_DATA_MODE"] = "bigquery"
    os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    os.environ.pop("GCP_PROJECT", None)

    from finance_ops.lib.fixtures import reload_fixtures
    from finance_ops.tools.bigquery_tools import bigquery_status
    from finance_ops.tools.invoice_tools import aging_summary
    from pipelines.batch.ingest import ingest_batch

    reload_fixtures()
    ingest_batch(run_id="smoke-master-l3")
    status = bigquery_status()
    aging = aging_summary("CUST-ACME")
    report["checks"]["l3_bigquery_fallback"] = {
        "ok": status.get("active_source") == "duckdb_fallback"
        and aging.get("invoice_count") == 2,
        "active_source": status.get("active_source"),
        "aging_total": aging.get("total_open"),
    }

    # #8: approval + slack notify path (no webhook → sent=false but links present)
    os.environ.pop("SLACK_WEBHOOK_URL", None)
    from finance_ops.tools.runtime_tools import get_approval, request_approval

    created = request_approval(
        kind="write_off",
        amount=50.0,
        summary="master-layer smoke",
        related_ids="INV-1001",
        notify_slack=True,
    )
    appr_id = created["approval"]["approval_id"]
    got = get_approval(appr_id)
    report["checks"]["hitl_slack_shape"] = {
        "ok": created.get("status") == "pending"
        and "approve" in (created.get("links") or {})
        and got.get("approval", {}).get("status") == "pending",
        "approval_id": appr_id,
        "slack_sent": (created.get("slack") or {}).get("sent"),
        "has_links": bool(created.get("links")),
    }

    ok = all(c.get("ok") for c in report["checks"].values())
    report["status"] = "PASS" if ok else "FAIL"
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
