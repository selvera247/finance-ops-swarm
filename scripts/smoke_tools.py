#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finance_ops.tools.graph_tools import graph_neighborhood  # noqa: E402
from finance_ops.tools.invoice_tools import aging_summary  # noqa: E402
from finance_ops.tools.payment_tools import suggest_payment_match  # noqa: E402


def main() -> None:
    for payload in (
        aging_summary("CUST-ACME"),
        suggest_payment_match("PAY-9002"),
        graph_neighborhood("PAY-9002", max_hops=2),
    ):
        print(json.dumps(payload, indent=2, default=str))
        print("-" * 40)


if __name__ == "__main__":
    main()
