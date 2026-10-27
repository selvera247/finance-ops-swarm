#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FINANCE_OPS_DATA_MODE", "warehouse")


def main() -> int:
    from data_plane.features.compute import compute_customer_features
    from data_plane.vectors.embed import build_policy_index, search
    from finance_ops.tools.bigquery_tools import bigquery_status
    from finance_ops.tools.feature_tools import lookup_customer_risk
    from finance_ops.tools.invoice_tools import aging_summary
    from finance_ops.tools.payment_tools import suggest_payment_match
    from finance_ops.tools.rag_tools import search_policies
    from pipelines.batch.ingest import ingest_batch
    from pipelines.stream.simulator import flush_stream_to_warehouse, seed_demo_stream

    report: dict = {"stages": {}}
    print("=== 1/5 Batch ingest ===")
    report["stages"]["batch"] = ingest_batch()
    print(json.dumps(report["stages"]["batch"], indent=2))

    print("\n=== 2/5 Streaming simulator ===")
    seeded = seed_demo_stream()
    flushed = flush_stream_to_warehouse()
    report["stages"]["stream"] = {"seeded": len(seeded), "flush": flushed}
    print(json.dumps(report["stages"]["stream"], indent=2))

    print("\n=== 3/5 Feature compute ===")
    report["stages"]["features"] = compute_customer_features()
    print(json.dumps(report["stages"]["features"], indent=2))

    print("\n=== 4/5 Vector index ===")
    report["stages"]["vectors"] = build_policy_index()
    report["stages"]["vector_search_sample"] = search("collections escalation past due")
    print(json.dumps(report["stages"]["vectors"], indent=2))

    print("\n=== 5/5 Agent tool smoke ===")
    smoke = {
        "aging_acme": aging_summary("CUST-ACME"),
        "match_pay_9002": suggest_payment_match("PAY-9002"),
        "risk_north": lookup_customer_risk("CUST-NORTH"),
        "policy": search_policies("write off unmatched payment"),
        "platform": bigquery_status(),
    }
    report["stages"]["agent_smoke"] = {
        "aging_total": smoke["aging_acme"].get("total_open"),
        "match_recommendation": smoke["match_pay_9002"].get("recommendation"),
        "north_risk": (smoke["risk_north"].get("features") or {}).get("risk_band"),
        "policy_hits": [h["doc_id"] for h in smoke["policy"].get("hits", [])],
        "data_mode": smoke["platform"].get("data_mode"),
        "warehouse_counts": smoke["platform"].get("warehouse_counts"),
    }
    print(json.dumps(report["stages"]["agent_smoke"], indent=2))

    out = ROOT / ".warehouse" / "e2e_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out}")
    ok = (
        report["stages"]["batch"]["status"] == "success"
        and report["stages"]["features"]["status"] == "success"
        and report["stages"]["vectors"]["status"] == "success"
        and smoke["aging_acme"]["invoice_count"] >= 2
        and smoke["match_pay_9002"].get("recommendation") is not None
    )
    print("\nE2E Data→AI:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
