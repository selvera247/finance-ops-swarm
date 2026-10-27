from __future__ import annotations

from finance_ops.runtime.sandbox import (
    build_container_cmd,
    resolve_isolation,
    run_calc,
    run_python,
    sandbox_isolation_status,
)
from finance_ops.tools.sandbox_tools import run_sandboxed_calc, run_sandboxed_python, sandbox_status


def test_calc_amount_tolerance() -> None:
    out = run_calc(
        "abs(payment - invoice) <= max(1.0, invoice * 0.005)",
        {"payment": 1842.5, "invoice": 1842.5},
    )
    assert out["status"] == "success"
    assert out["result"] is True


def test_calc_rejects_attribute_and_imports() -> None:
    out = run_calc("__import__('os').system('echo x')", {})
    assert out["status"] in {"error", "denied"}


def test_calc_policy_wall() -> None:
    out = run_calc("apply_payment_match", {"apply_payment_match": 1})
    assert out["status"] == "denied"


def test_python_sum_lines() -> None:
    out = run_python(
        "RESULT = round(sum(inputs['lines']), 2)",
        {"lines": [100.0, 50.25, 12.0]},
        isolation="subprocess",
    )
    assert out["status"] == "success"
    assert out["result"] == 162.25
    assert out.get("isolation") == "subprocess_python_-I"


def test_python_blocks_os_import() -> None:
    out = run_python("import os\nRESULT = os.getcwd()", {}, isolation="subprocess")
    assert out["status"] in {"error", "denied"}


def test_python_blocks_finance_ops_name() -> None:
    out = run_python("RESULT = 'finance_ops'", {}, isolation="subprocess")
    assert out["status"] == "denied"


def test_tool_wrappers_evidence() -> None:
    calc = run_sandboxed_calc("payment + 1", '{"payment": 10}')
    assert calc["status"] == "success"
    assert calc["result"] == 11
    assert "evidence_id" in calc["evidence"]

    py = run_sandboxed_python("RESULT = inputs['n'] * 2", '{"n": 21}')
    assert py["status"] == "success"
    assert py["result"] == 42
    assert "evidence_id" in py["evidence"]


def test_container_cmd_flags() -> None:
    cmd = build_container_cmd(image="finance-ops-sandbox:test", memory="128m", cpus="0.25", runtime="runsc")
    assert "--network=none" in cmd
    assert "--read-only" in cmd
    assert "--runtime" in cmd and "runsc" in cmd
    assert "finance-ops-sandbox:test" in cmd
    assert cmd[0]  # docker bin


def test_resolve_isolation_subprocess_forced(monkeypatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_SANDBOX_ISOLATION", "subprocess")
    effective, reason = resolve_isolation()
    assert effective == "subprocess"
    assert reason is None


def test_resolve_isolation_container_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("FINANCE_OPS_SANDBOX_ISOLATION", "container")
    monkeypatch.setattr("finance_ops.runtime.sandbox.docker_available", lambda: False)
    effective, reason = resolve_isolation()
    assert effective == "subprocess"
    assert reason == "docker_unavailable"


def test_container_request_falls_back_and_runs(monkeypatch) -> None:
    monkeypatch.setattr("finance_ops.runtime.sandbox.docker_available", lambda: False)
    out = run_python("RESULT = 2 + 2", {}, isolation="container")
    assert out["status"] == "success"
    assert out["result"] == 4
    assert out.get("isolation_fallback") == "docker_unavailable"
    assert out.get("isolation") == "subprocess_python_-I"


def test_sandbox_status_tool() -> None:
    st = sandbox_status()
    assert st["status"] == "success"
    assert st["effective"] in {"subprocess", "container"}
    assert "evidence_id" in st["evidence"]
    snap = sandbox_isolation_status()
    assert "docker_available" in snap
