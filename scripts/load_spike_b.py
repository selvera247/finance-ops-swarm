#!/usr/bin/env python3
"""Load Spike B remittance exceptions into portal_extracts via drop-zone ingest.

Stages data/spike_b/remittance_exceptions.csv into
data/incoming/payer_availity/ and runs process_incoming.

Usage:
  PYTHONPATH=. python scripts/load_spike_b.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SPIKE_DIR = ROOT / "data" / "spike_b"
SOURCE = SPIKE_DIR / "remittance_exceptions.csv"
PORTAL_ID = "payer_availity"
WALKTHROUGH = ("CLM-B1001", "CLM-B2001", "CLM-B3001")


def load() -> dict:
    from data_plane.config import INCOMING_DIR, ensure_dirs
    from data_plane import repository as repo
    from data_plane.warehouse import db
    from gui_connectors.ingest.portal_ingest import process_incoming

    if not SOURCE.is_file():
        return {"status": "error", "error": f"missing {SOURCE}"}

    ensure_dirs()
    db.init_schema()
    dest_dir = INCOMING_DIR / PORTAL_ID
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "spike_b_remittance_exceptions.csv"
    shutil.copy2(SOURCE, dest)

    watcher = process_incoming(PORTAL_ID)
    rows = repo.portal_extracts(portal_id=PORTAL_ID)
    spike_rows = [
        r
        for r in rows
        if str(r.get("external_id") or "").startswith("CLM-B")
        or "spike_b" in str(r.get("source_file") or "")
    ]
    rows_ingested = sum(int(r.get("rows") or 0) for r in (watcher.get("results") or []))
    return {
        "status": "success" if watcher.get("status") in {"success", "partial"} and spike_rows else watcher.get("status", "error"),
        "portal_id": PORTAL_ID,
        "staged": str(dest),
        "watcher": {
            "files_processed": watcher.get("files_processed"),
            "rows_ingested": rows_ingested,
            "status": watcher.get("status"),
        },
        "counts": {
            "portal_extracts_portal": len(rows),
            "spike_b_rows": len(spike_rows),
        },
        "walkthrough": list(WALKTHROUGH),
        "needs_review": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Load Spike B portal extract sample")
    parser.parse_args()
    result = load()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
