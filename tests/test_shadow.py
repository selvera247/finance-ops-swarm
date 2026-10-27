from __future__ import annotations

import json
from pathlib import Path

from data_plane import repository as repo
from finance_ops.runtime.shadow import ShadowStore, build_cash_app_shadow, build_spike_a_shadow_bundle
from finance_ops.tools.shadow_tools import (
    get_shadow_trajectory,
    shadow_cash_app_trajectory,
    shadow_spike_a_walkthrough,
)


def test_shadow_cash_app_does_not_mutate(tmp_path: Path) -> None:
    store = ShadowStore(root=tmp_path / "shadow")
    before = repo.get_payment("PAY-9002")
    assert before is not None
    status_before = before.get("status")

    traj = build_cash_app_shadow("PAY-9002", store=store)
    assert traj.status == "closed"
    assert traj.would_mutate is True
    assert any(s.tool == "suggest_payment_match" and s.side_effect == "read_ok" for s in traj.steps)
    assert any(s.tool == "request_cash_app_approval" and s.side_effect == "shadow_skipped" for s in traj.steps)
    assert any(s.tool == "apply_payment_match" and s.side_effect == "shadow_skipped" for s in traj.steps)

    after = repo.get_payment("PAY-9002")
    assert after is not None
    assert after.get("status") == status_before
    assert after.get("matched_invoice_id") == before.get("matched_invoice_id")


def test_shadow_tool_wrapper_evidence() -> None:
    out = shadow_cash_app_trajectory("PAY-9002")
    assert out["status"] == "success"
    assert out["mutated"] is False
    assert "evidence_id" in out["evidence"]
    tid = out["trajectory"]["trajectory_id"]
    loaded = get_shadow_trajectory(tid)
    assert loaded["status"] == "success"
    assert loaded["trajectory"]["trajectory_id"] == tid


def test_spike_a_bundle_when_loaded() -> None:
    """If Spike A CSV was loaded, walkthrough ids resolve; else skip gracefully."""
    p = repo.get_payment("PAY-1001")
    if not p:
        traj = build_cash_app_shadow("PAY-1001")
        assert traj.steps[0].status in {"not_found", "success"}
        return
    bundle = build_spike_a_shadow_bundle()
    assert bundle["mutated"] is False
    assert len(bundle["trajectories"]) == 3
    assert Path(bundle["path"]).is_file()
    raw = json.loads(Path(bundle["path"]).read_text(encoding="utf-8"))
    assert raw["bundle_id"] == bundle["bundle_id"]

    tool = shadow_spike_a_walkthrough()
    assert tool["mutated"] is False
    assert tool["bundle"]["kind"] == "spike_a_walkthrough"
