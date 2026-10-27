"""C7 sandboxed execution: calc (A) + Python (B) + policy wall (D) + container (C).

Policy (D): sandboxed code never receives write-tool handles, credentials, or
``finance_ops`` / ``data_plane`` imports. It may only return numbers / tables;
typed agent tools + HITL remain the only mutation path.

Isolation (C7-C): ``FINANCE_OPS_SANDBOX_ISOLATION=subprocess|container|auto``
runs the same worker in Docker with ``--network=none`` (optional gVisor runtime).
"""

from __future__ import annotations

import ast
import json
import operator
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

# Soft ceiling so agents cannot dump huge scripts into the tool.
_MAX_CODE_CHARS = 8_000
_DEFAULT_TIMEOUT_S = 2.0
_DEFAULT_IMAGE = "finance-ops-sandbox:latest"

Isolation = Literal["subprocess", "container", "auto"]

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_ALLOWED_CALLS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "float": float,
    "int": int,
}

_POLICY_BLOCKLIST = (
    "finance_ops",
    "data_plane",
    "apply_payment_match",
    "decide_approval",
    "request_approval",
    "subprocess",
    "os.environ",
    "open(",
    "__import__",
)


def _timeout_s() -> float:
    raw = os.environ.get("FINANCE_OPS_SANDBOX_TIMEOUT", "")
    try:
        return max(0.25, float(raw)) if raw else _DEFAULT_TIMEOUT_S
    except ValueError:
        return _DEFAULT_TIMEOUT_S


def _policy_scan(code: str) -> str | None:
    lowered = code.lower()
    for needle in _POLICY_BLOCKLIST:
        if needle.lower() in lowered:
            return f"policy wall blocked pattern: {needle}"
    return None


def isolation_mode() -> Isolation:
    raw = (os.environ.get("FINANCE_OPS_SANDBOX_ISOLATION") or "auto").strip().lower()
    if raw in {"subprocess", "container", "auto"}:
        return raw  # type: ignore[return-value]
    return "auto"


def sandbox_image() -> str:
    return (os.environ.get("FINANCE_OPS_SANDBOX_IMAGE") or _DEFAULT_IMAGE).strip()


def docker_bin() -> str:
    return (os.environ.get("FINANCE_OPS_SANDBOX_DOCKER") or "docker").strip() or "docker"


def docker_runtime() -> str | None:
    """Optional OCI runtime (e.g. ``runsc`` for gVisor)."""
    raw = (os.environ.get("FINANCE_OPS_SANDBOX_RUNTIME") or "").strip()
    return raw or None


def docker_available() -> bool:
    exe = docker_bin()
    if not shutil.which(exe) and not Path(exe).is_file():
        return False
    try:
        proc = subprocess.run(
            [exe, "info"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def image_present(image: str | None = None) -> bool:
    image = image or sandbox_image()
    exe = docker_bin()
    try:
        proc = subprocess.run(
            [exe, "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def resolve_isolation(requested: Isolation | None = None) -> tuple[str, str | None]:
    """Return ``(effective_isolation, fallback_reason)``."""
    mode = requested or isolation_mode()
    if mode == "subprocess":
        return "subprocess", None
    if mode == "container":
        if not docker_available():
            return "subprocess", "docker_unavailable"
        if not image_present():
            return "subprocess", "image_missing"
        return "container", None
    # auto
    if docker_available() and image_present():
        return "container", None
    if not docker_available():
        return "subprocess", "docker_unavailable"
    return "subprocess", "image_missing"


class _SafeCalc(ast.NodeVisitor):
    """Evaluate a pure arithmetic / comparison expression against ``names``."""

    def __init__(self, names: dict[str, Any]) -> None:
        self.names = names

    def visit(self, node: ast.AST) -> Any:  # type: ignore[override]
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, bool, str)) or node.value is None:
                return node.value
            raise ValueError(f"constant type not allowed: {type(node.value).__name__}")
        if isinstance(node, ast.Name):
            if node.id not in self.names:
                raise ValueError(f"unknown name: {node.id}")
            return self.names[node.id]
        if isinstance(node, ast.BinOp):
            op = _BIN_OPS.get(type(node.op))
            if op is None:
                raise ValueError("operator not allowed")
            return op(self.visit(node.left), self.visit(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _UNARY_OPS.get(type(node.op))
            if op is None:
                raise ValueError("unary operator not allowed")
            return op(self.visit(node.operand))
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                val: Any = True
                for v in node.values:
                    val = self.visit(v)
                    if not val:
                        return val
                return val
            if isinstance(node.op, ast.Or):
                val = False
                for v in node.values:
                    val = self.visit(v)
                    if val:
                        return val
                return val
            raise ValueError("bool operator not allowed")
        if isinstance(node, ast.Compare):
            left = self.visit(node.left)
            for op_node, comparator in zip(node.ops, node.comparators):
                op = _CMP_OPS.get(type(op_node))
                if op is None:
                    raise ValueError("comparison not allowed")
                right = self.visit(comparator)
                if not op(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS:
                raise ValueError("function call not allowed")
            if node.keywords:
                raise ValueError("keyword args not allowed in calc")
            fn = _ALLOWED_CALLS[node.func.id]
            return fn(*(self.visit(a) for a in node.args))
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self.visit(elt) for elt in node.elts]
        if isinstance(node, ast.Dict):
            return {self.visit(k): self.visit(v) for k, v in zip(node.keys, node.values) if k is not None}
        raise ValueError(f"expression node not allowed: {type(node).__name__}")


def run_calc(expression: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """A — evaluate a safe arithmetic expression; ``inputs`` bind as names."""
    expression = (expression or "").strip()
    inputs = dict(inputs or {})
    if not expression:
        return {"status": "error", "mode": "calc", "error": "empty expression", "needs_review": True}
    if len(expression) > _MAX_CODE_CHARS:
        return {"status": "error", "mode": "calc", "error": "expression too long", "needs_review": True}
    blocked = _policy_scan(expression)
    if blocked:
        return {"status": "denied", "mode": "calc", "error": blocked, "needs_review": True, "policy": "D"}
    try:
        tree = ast.parse(expression, mode="eval")
        value = _SafeCalc(inputs).visit(tree)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "mode": "calc",
            "error": str(exc),
            "needs_review": True,
        }
    return {
        "status": "success",
        "mode": "calc",
        "result": value,
        "needs_review": False,
        "policy": "no_side_effects",
    }


def _parse_worker_stdout(stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    if not (stdout or "").strip():
        return {
            "status": "error",
            "mode": "python",
            "error": (stderr or "").strip() or f"empty stdout (exit {returncode})",
            "needs_review": True,
        }
    try:
        body = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "status": "error",
            "mode": "python",
            "error": f"worker non-json: {stdout[:400]}",
            "stderr": (stderr or "")[:400],
            "needs_review": True,
        }
    if not body.get("ok"):
        return {
            "status": "error",
            "mode": "python",
            "error": body.get("error", "worker failed"),
            "needs_review": True,
            "policy": "D",
        }
    return {
        "status": "success",
        "mode": "python",
        "result": body.get("result"),
        "needs_review": False,
        "policy": "no_side_effects",
    }


def build_container_cmd(
    *,
    image: str | None = None,
    memory: str | None = None,
    cpus: str | None = None,
    runtime: str | None = None,
) -> list[str]:
    """Docker argv for a no-network, read-only guest (stdin/stdout JSON)."""
    image = image or sandbox_image()
    memory = memory or os.environ.get("FINANCE_OPS_SANDBOX_MEM", "256m")
    cpus = cpus or os.environ.get("FINANCE_OPS_SANDBOX_CPUS", "0.5")
    runtime = runtime if runtime is not None else docker_runtime()
    cmd = [
        docker_bin(),
        "run",
        "--rm",
        "-i",
        "--network=none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--memory",
        memory,
        "--cpus",
        cpus,
        "--user",
        "10001:10001",
        "-e",
        "HOME=/tmp",
        "-e",
        "PYTHONNOUSERSITE=1",
    ]
    if runtime:
        cmd.extend(["--runtime", runtime])
    cmd.append(image)
    return cmd


def _run_subprocess_worker(payload: str, timeout: float) -> dict[str, Any]:
    worker_src = (Path(__file__).resolve().parent / "sandbox_worker.py").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="fo_sandbox_") as tmp:
        worker = Path(tmp) / "worker.py"
        worker.write_text(worker_src, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(worker)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
                env={},
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "mode": "python",
                "error": f"exceeded {timeout}s",
                "needs_review": True,
                "policy": "D",
                "isolation": "subprocess_python_-I",
            }
        except OSError as exc:
            return {
                "status": "error",
                "mode": "python",
                "error": f"spawn failed: {exc}",
                "needs_review": True,
                "isolation": "subprocess_python_-I",
            }
    out = _parse_worker_stdout(proc.stdout, proc.stderr, proc.returncode)
    out["isolation"] = "subprocess_python_-I"
    if out.get("status") == "success":
        out["note"] = "Subprocess isolation (C7-B). Set FINANCE_OPS_SANDBOX_ISOLATION=container for C7-C."
    return out


def _run_container_worker(payload: str, timeout: float) -> dict[str, Any]:
    cmd = build_container_cmd()
    # docker run needs headroom beyond guest timeout
    docker_timeout = max(timeout + 5.0, timeout * 2)
    try:
        proc = subprocess.run(
            cmd,
            input=payload,
            capture_output=True,
            text=True,
            timeout=docker_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "mode": "python",
            "error": f"container exceeded {timeout}s guest budget",
            "needs_review": True,
            "policy": "D",
            "isolation": "container_docker",
        }
    except OSError as exc:
        return {
            "status": "error",
            "mode": "python",
            "error": f"docker spawn failed: {exc}",
            "needs_review": True,
            "isolation": "container_docker",
        }
    out = _parse_worker_stdout(proc.stdout, proc.stderr, proc.returncode)
    runtime = docker_runtime()
    out["isolation"] = f"container_docker{'_'+runtime if runtime else ''}"
    out["image"] = sandbox_image()
    if out.get("status") == "success":
        out["note"] = "C7-C container isolation (--network=none, read-only rootfs)."
    elif proc.returncode != 0 and not (proc.stdout or "").strip():
        out["error"] = out.get("error") or (proc.stderr or "")[:400] or f"docker exit {proc.returncode}"
    return out


def run_python(
    code: str,
    inputs: dict[str, Any] | None = None,
    *,
    isolation: Isolation | None = None,
) -> dict[str, Any]:
    """B/C — run short Python in subprocess or Docker container.

    Guest code should assign ``RESULT = ...`` (or ``result``). Only JSON-serializable
    values are returned.
    """
    code = code or ""
    inputs = dict(inputs or {})
    if not code.strip():
        return {"status": "error", "mode": "python", "error": "empty code", "needs_review": True}
    if len(code) > _MAX_CODE_CHARS:
        return {"status": "error", "mode": "python", "error": "code too long", "needs_review": True}
    blocked = _policy_scan(code)
    if blocked:
        return {"status": "denied", "mode": "python", "error": blocked, "needs_review": True, "policy": "D"}

    payload = json.dumps({"code": code, "inputs": inputs}, default=str)
    timeout = _timeout_s()
    effective, fallback_reason = resolve_isolation(isolation)

    if effective == "container":
        out = _run_container_worker(payload, timeout)
    else:
        out = _run_subprocess_worker(payload, timeout)
        if fallback_reason:
            out["isolation_fallback"] = fallback_reason
            if isolation == "container":
                out["note"] = (
                    f"Requested container isolation but fell back ({fallback_reason}). "
                    "Build image: bash scripts/build_sandbox_image.sh"
                )
    return out


def sandbox_isolation_status() -> dict[str, Any]:
    """Ops helper: which isolation would run_python use right now."""
    effective, reason = resolve_isolation()
    return {
        "status": "success",
        "requested": isolation_mode(),
        "effective": effective,
        "fallback_reason": reason,
        "docker_available": docker_available(),
        "image": sandbox_image(),
        "image_present": image_present() if docker_available() else False,
        "runtime": docker_runtime(),
        "needs_review": False,
    }
