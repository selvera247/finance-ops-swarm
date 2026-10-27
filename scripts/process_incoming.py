#!/usr/bin/env python3
"""Drain data/incoming/<portal_id>/*.csv into warehouse.portal_extracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portal", default=None, help="Optional portal_id filter")
    args = parser.parse_args()

    from gui_connectors.ingest.portal_ingest import process_incoming
    from pipelines.batch.ingest import ingest_batch

    ingest_batch(run_id="pre-incoming-batch")
    result = process_incoming(args.portal)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") in {"success", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
