"""Generic portal extract ingest: CSV → warehouse.portal_extracts.

Supports per-portal drop zones under data/incoming/<portal_id>/ and known
CSV shapes for:
  - legacy_bank / bank_statement
  - sagesure / policy_status (demo)
  - payer_* / claim_status or remittance (demo)
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_plane.config import INCOMING_DIR, ensure_dirs
from data_plane.warehouse import db

# Column aliases → canonical fields
_FIELD_MAP = {
    "external_id": ("statement_id", "policy_id", "claim_id", "external_id", "id"),
    "entity_id": ("account_id", "agency_id", "patient_id", "entity_id", "carrier_id"),
    "txn_date": ("txn_date", "as_of_date", "service_date", "statement_date", "date"),
    "amount": ("amount", "premium", "paid_amount", "commission", "balance"),
    "currency": ("currency", "ccy"),
    "description": ("description", "desc", "notes", "line_desc"),
    "status": ("status", "policy_status", "claim_status", "bind_status"),
}

_DEFAULT_EXTRACT_TYPE = {
    "legacy_bank": "bank_statement",
    "sagesure": "policy_status",
    "payer_availity": "claim_status",
}


def _pick(row: dict[str, str], keys: tuple[str, ...]) -> str | None:
    lower = {k.lower().strip(): v for k, v in row.items() if k}
    for key in keys:
        if key in lower and lower[key] not in (None, ""):
            return str(lower[key]).strip()
    return None


def _extract_id(portal_id: str, source_file: str, row: dict[str, str], idx: int) -> str:
    basis = f"{portal_id}|{source_file}|{idx}|{json.dumps(row, sort_keys=True)}"
    return hashlib.sha256(basis.encode()).hexdigest()[:24]


def _infer_extract_type(portal_id: str, row: dict[str, str]) -> str:
    cols = {k.lower() for k in row}
    if "claim_id" in cols or "trn" in cols:
        return "claim_status" if "paid_amount" not in cols else "remittance"
    if "policy_id" in cols or "bind_status" in cols:
        return "policy_status"
    if "statement_id" in cols or "account_id" in cols:
        return "bank_statement"
    return _DEFAULT_EXTRACT_TYPE.get(portal_id, "portal_row")


def ingest_portal_csv(
    portal_id: str,
    path: str | Path,
    *,
    extract_type: str | None = None,
    also_legacy_bank_table: bool = True,
) -> dict[str, Any]:
    """Ingest one portal CSV into portal_extracts (+ bank_statements when applicable)."""
    path = Path(path)
    if not path.exists():
        return {"status": "error", "error": f"file not found: {path}"}

    ensure_dirs()
    db.init_schema()
    now = datetime.now(timezone.utc)
    batch_id = f"portal-{uuid.uuid4().hex[:10]}"
    rows_written = 0
    bank_written = 0

    con = db.connect()
    try:
        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for idx, row in enumerate(reader):
                etype = extract_type or _infer_extract_type(portal_id, row)
                external_id = _pick(row, _FIELD_MAP["external_id"])
                entity_id = _pick(row, _FIELD_MAP["entity_id"])
                txn_date = _pick(row, _FIELD_MAP["txn_date"])
                amount_raw = _pick(row, _FIELD_MAP["amount"])
                try:
                    amount = float(amount_raw) if amount_raw is not None else None
                except ValueError:
                    amount = None
                currency = _pick(row, _FIELD_MAP["currency"]) or "USD"
                description = _pick(row, _FIELD_MAP["description"])
                status = _pick(row, _FIELD_MAP["status"])
                extract_id = _extract_id(portal_id, path.name, row, idx)

                con.execute(
                    """
                    INSERT OR REPLACE INTO portal_extracts VALUES (
                      ?,?,?,?,?,?,?,?,?,?,?,?,?,?
                    )
                    """,
                    [
                        extract_id,
                        portal_id,
                        etype,
                        external_id,
                        entity_id,
                        txn_date,
                        amount,
                        currency,
                        description,
                        status,
                        json.dumps(row),
                        path.name,
                        batch_id,
                        now,
                    ],
                )
                rows_written += 1

                if (
                    also_legacy_bank_table
                    and etype == "bank_statement"
                    and portal_id in {"legacy_bank", "bank"}
                ):
                    con.execute(
                        "INSERT INTO bank_statements VALUES (?,?,?,?,?,?,?,?)",
                        [
                            external_id,
                            entity_id,
                            txn_date,
                            description,
                            amount or 0.0,
                            currency,
                            path.name,
                            now,
                        ],
                    )
                    bank_written += 1

        con.execute(
            "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?,?,?)",
            [
                batch_id,
                "portal_extract_ingest",
                "success",
                json.dumps(
                    {
                        "portal_id": portal_id,
                        "rows": rows_written,
                        "bank_rows": bank_written,
                        "file": path.name,
                    }
                ),
                now,
                now,
            ],
        )
        return {
            "status": "success",
            "portal_id": portal_id,
            "rows": rows_written,
            "bank_statement_rows": bank_written,
            "source_file": path.name,
            "batch_id": batch_id,
        }
    finally:
        con.close()


def stage_file_to_incoming(portal_id: str, path: str | Path) -> Path:
    """Copy a downloaded file into data/incoming/<portal_id>/."""
    ensure_dirs()
    path = Path(path)
    dest_dir = INCOMING_DIR / portal_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.copy2(path, dest)
    return dest


def process_incoming(portal_id: str | None = None) -> dict[str, Any]:
    """Watch-style batch: ingest CSVs from data/incoming/<portal>/ then move to processed/."""
    ensure_dirs()
    results: list[dict[str, Any]] = []
    portals = [INCOMING_DIR / portal_id] if portal_id else sorted(INCOMING_DIR.iterdir())

    for portal_dir in portals:
        if not portal_dir.is_dir() or portal_dir.name.startswith("."):
            continue
        if portal_dir.name == "processed":
            continue
        processed = portal_dir / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        for csv_path in sorted(portal_dir.glob("*.csv")):
            ingest = ingest_portal_csv(portal_dir.name, csv_path)
            if ingest.get("status") == "success":
                target = processed / csv_path.name
                if target.exists():
                    target = processed / f"{csv_path.stem}_{uuid.uuid4().hex[:6]}{csv_path.suffix}"
                # Keep checked-in sample_*.csv in place; move only runtime drops
                if csv_path.name.startswith("sample_"):
                    shutil.copy2(csv_path, target)
                    ingest["copied_to"] = str(target)
                else:
                    shutil.move(str(csv_path), str(target))
                    ingest["moved_to"] = str(target)
            results.append(ingest)

    ok = all(r.get("status") == "success" for r in results) if results else True
    return {
        "status": "success" if ok else "partial",
        "files_processed": len(results),
        "results": results,
    }


# Back-compat alias
def ingest_bank_statement_csv(path: str | Path) -> dict[str, Any]:
    """Deprecated name — stages into incoming/legacy_bank then ingests."""
    staged = stage_file_to_incoming("legacy_bank", path)
    return ingest_portal_csv("legacy_bank", staged, extract_type="bank_statement")
