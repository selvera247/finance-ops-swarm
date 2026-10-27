from __future__ import annotations

import shutil
from pathlib import Path

from data_plane.config import INCOMING_DIR, REPO_ROOT
from data_plane import repository as repo
from gui_connectors.ingest.portal_ingest import process_incoming
from pipelines.batch.ingest import ingest_batch


def test_incoming_watcher_sagesure_and_payer():
    ingest_batch(run_id="portal-test-batch")

    # Re-seed sample CSVs into drop zones (may have been moved by prior runs)
    samples = {
        "sagesure": REPO_ROOT / "data/incoming/sagesure/sample_policy_status.csv",
        "payer_availity": REPO_ROOT / "data/incoming/payer_availity/sample_claim_status.csv",
    }
    for portal, sample in samples.items():
        processed = list((INCOMING_DIR / portal / "processed").glob(sample.name))
        dest = INCOMING_DIR / portal / sample.name
        if not dest.exists() and processed:
            shutil.copy2(processed[0], dest)
        assert dest.exists() or sample.exists()
        if not dest.exists():
            shutil.copy2(sample, dest)

    result = process_incoming()
    assert result["files_processed"] >= 2
    assert result["status"] in {"success", "partial"}

    sagesure = repo.portal_extracts(portal_id="sagesure", extract_type="policy_status")
    assert len(sagesure) >= 3
    assert any(r["external_id"] == "POL-8801" for r in sagesure)

    payer = repo.portal_extracts(portal_id="payer_availity")
    assert len(payer) >= 3
    assert any(r["external_id"] == "CLM-5001" for r in payer)


def test_bank_csv_writes_portal_extracts_and_compat_table():
    ingest_batch(run_id="bank-portal-unit")
    from gui_connectors.ingest.portal_ingest import ingest_portal_csv

    csv_path = REPO_ROOT / "data/incoming/legacy_bank/_unit_bank.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(
        "statement_id,account_id,txn_date,description,amount,currency\n"
        "STMT-U1,ACC-1001,2026-09-01,Unit wire,100.00,USD\n",
        encoding="utf-8",
    )
    out = ingest_portal_csv("legacy_bank", csv_path, extract_type="bank_statement")
    assert out["status"] == "success"
    assert out["rows"] == 1
    assert out["bank_statement_rows"] == 1

    extracts = repo.portal_extracts(portal_id="legacy_bank", entity_id="ACC-1001")
    assert any(r["external_id"] == "STMT-U1" for r in extracts)
    assert len(repo.bank_statements("ACC-1001")) >= 1
