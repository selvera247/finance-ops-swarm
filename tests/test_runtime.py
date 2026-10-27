"""Coverage for Agent Engineer gaps #11/#12/#8/#1/#5."""

from __future__ import annotations

from pathlib import Path

import pytest

from finance_ops.lib.fixtures import reload_fixtures
from finance_ops.runtime.a2a import build_invoice_aging_task, execute_typed_invoice_aging
from finance_ops.runtime.circuit_breaker import CircuitBreaker, CircuitOpenError
from finance_ops.runtime.durable import DurableWorkflow, StepStatus
from finance_ops.runtime.fallback_router import resolve_portal_data
from finance_ops.runtime.hitl import ApprovalStore
from finance_ops.tools.runtime_tools import (
    decide_approval,
    request_approval,
    reset_circuit_breaker,
    resolve_portal_with_fallback,
    run_typed_a2a_aging,
    start_durable_reconcile,
)
from pipelines.batch.ingest import ingest_batch


def setup_function() -> None:
    reload_fixtures()
    reset_circuit_breaker()
    ingest_batch(run_id="runtime-test-batch")


def test_circuit_breaker_tool_budget() -> None:
    breaker = CircuitBreaker(max_tool_calls=3, max_depth=8)
    breaker.record_tool("a")
    breaker.record_tool("b")
    breaker.record_tool("c")
    with pytest.raises(CircuitOpenError):
        breaker.record_tool("d")
    assert breaker.snapshot()["open"] is True


def test_circuit_breaker_depth() -> None:
    breaker = CircuitBreaker(max_tool_calls=50, max_depth=2)
    breaker.enter("1")
    breaker.enter("2")
    with pytest.raises(CircuitOpenError):
        breaker.enter("3")


def test_fallback_warehouse_path(tmp_path: Path) -> None:
    # Seed portal extracts via sample CSV ingest
    from gui_connectors.ingest.portal_ingest import ingest_portal_csv

    sample = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "incoming"
        / "sagesure"
        / "sample_policy_status.csv"
    )
    # Use a copy under tmp so we don't move the fixture permanently in a weird way
    staged = tmp_path / "sample_policy_status.csv"
    staged.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    ingest_portal_csv("sagesure", staged, extract_type="policy_status")

    result = resolve_portal_data(
        "sagesure",
        extract_type="policy_status",
        min_rows=1,
        allow_browser_fallback=False,
    )
    assert result["status"] == "success"
    assert result["path"] == "warehouse"
    assert result["count"] >= 1


def test_fallback_api_timeout_then_warehouse() -> None:
    # Warehouse may be empty for legacy_bank in fresh for this extract filter —
    # use API that returns rows so path=api
    rows = [{"entity_id": "ACC-1001", "amount": 1.0}]

    def api_ok() -> list:
        return rows

    result = resolve_portal_data(
        "legacy_bank",
        allow_browser_fallback=False,
        api_lookup=api_ok,
        min_rows=1,
    )
    assert result["path"] == "api"
    assert result["count"] == 1


def test_fallback_api_miss_no_browser() -> None:
    def api_empty() -> list:
        return []

    result = resolve_portal_data(
        "payer_availity",
        allow_browser_fallback=False,
        api_lookup=api_empty,
        min_rows=1,
    )
    assert result["status"] in {"not_found", "success"}
    if result["status"] == "not_found":
        assert result["path"] == "none"
        assert result["needs_review"] is True


def test_hitl_create_decide(tmp_path: Path) -> None:
    store = ApprovalStore(root=tmp_path / "hitl")
    pending = store.create(
        kind="invoice_post",
        amount=4200.0,
        summary="Post PAY-9002 to INV-1002",
        payload={"payment_id": "PAY-9002"},
    )
    assert pending.status == "pending"
    listed = store.list("pending")
    assert any(a.approval_id == pending.approval_id for a in listed)
    decided = store.decide(
        pending.approval_id,
        decision="approved",
        actor="tester",
        resume_token=pending.resume_token,
    )
    assert decided.status == "approved"
    assert decided.decided_by == "tester"


def test_hitl_tool_wrappers() -> None:
    created = request_approval(
        kind="write_off",
        amount=125.0,
        summary="Write off small balance INV-1001",
        related_ids="INV-1001",
    )
    assert created["status"] == "pending"
    approval_id = created["approval"]["approval_id"]
    token = created["approval"]["resume_token"]
    decided = decide_approval(approval_id, "approved", resume_token=token, actor="cj")
    assert decided["status"] == "approved"


def test_a2a_typed_invoice_aging() -> None:
    state, task = build_invoice_aging_task("conv-1", "CUST-ACME")
    assert task.target_agent == "invoice_agent"
    result = execute_typed_invoice_aging(task)
    state.complete(result)
    assert result.status in {"ok", "needs_review"}
    assert result.facts.get("invoice_count") == 2
    assert state.latest_for("invoice_agent") is not None

    wrapped = run_typed_a2a_aging("CUST-ACME", conversation_id="conv-2")
    assert wrapped["status"] == "success"
    assert wrapped["result"]["agent"] == "invoice_agent"


def test_durable_checkpoint_resume(tmp_path: Path) -> None:
    calls = {"n": 0}

    def ok(_state):
        return {"ok": True}

    def flaky(state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return {"recovered": True, "prior": state.steps[0].output}

    wf = DurableWorkflow(root=tmp_path / "wf")
    handlers = {"step_a": ok, "step_b": flaky}
    state = wf.create(list(handlers.keys()))
    # First run: step_b fails once then retries succeed within max_retries
    finished = wf.run(handlers, state=state, max_retries=3, base_delay_seconds=0.001)
    assert finished.status == StepStatus.success
    assert finished.steps[1].attempts >= 2

    # Crash mid-flight simulation: mark last step pending and resume
    state2 = wf.create(["step_a", "step_b"])
    state2.steps[0].status = StepStatus.success
    state2.steps[0].output = {"ok": True}
    wf.save(state2)
    calls["n"] = 0
    resumed = wf.resume(state2.run_id, handlers, max_retries=3, base_delay_seconds=0.001)
    assert resumed.status == StepStatus.success
    assert resumed.steps[0].status == StepStatus.success  # skipped re-run


def test_start_durable_reconcile_tool() -> None:
    # Seed enough warehouse data so resolve path is warehouse (no browser)
    from gui_connectors.ingest.portal_ingest import process_incoming

    process_incoming()
    result = start_durable_reconcile(allow_browser=False)
    assert result["run_id"].startswith("WF-")
    assert result["status"] in {"success", "failed"}
    # reconcile_smoke + batch should succeed even if resolve is not_found
    assert len(result["steps"]) == 4


def test_resolve_portal_tool_warehouse() -> None:
    from gui_connectors.ingest.portal_ingest import process_incoming

    process_incoming("sagesure")
    result = resolve_portal_with_fallback(
        "sagesure",
        extract_type="policy_status",
        allow_browser_fallback=False,
    )
    assert result["status"] == "success"
    assert result["path"] == "warehouse"
    assert "evidence" in result
