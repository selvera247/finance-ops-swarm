"""Isolated worker for sandboxed Python (C7-B).

Invoked with ``python -I -m finance_ops.runtime.sandbox_worker`` so PYTHONPATH /
user site packages are ignored. Stdlib-only; never imports finance_ops tools.
Reads one JSON object from stdin: ``{"code": "...", "inputs": {...}}``.
Writes one JSON object to stdout.
"""

from __future__ import annotations

import ast
import json
import math
import sys
from typing import Any

_FORBIDDEN_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "ssl",
        "pathlib",
        "shutil",
        "ctypes",
        "multiprocessing",
        "threading",
        "signal",
        "importlib",
        "builtins",
        "code",
        "codeop",
        "pty",
        "fcntl",
        "resource",
        "http",
        "urllib",
        "requests",
        "finance_ops",
        "data_plane",
        "pipelines",
        "gui_connectors",
    }
)

_ALLOWED_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "pow": pow,
    "range": range,
    "round": round,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}


def _safe_import(name: str, globals: Any = None, locals: Any = None, fromlist: tuple = (), level: int = 0):  # noqa: A002
    root = name.split(".", 1)[0]
    if root in _FORBIDDEN_MODULES or name.startswith("_"):
        raise ImportError(f"import blocked in sandbox: {name}")
    # Allow a tiny math-only surface; everything else denied.
    if root == "math":
        return math
    raise ImportError(f"import blocked in sandbox: {name}")


def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise ValueError("global/nonlocal not allowed in sandbox")
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("_"):
            raise ValueError("private attribute access blocked")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001
        json.dump({"ok": False, "error": f"invalid stdin json: {exc}"}, sys.stdout)
        return 1

    code = payload.get("code") or ""
    inputs = payload.get("inputs") or {}
    if not isinstance(code, str) or not isinstance(inputs, dict):
        json.dump({"ok": False, "error": "code must be str and inputs must be object"}, sys.stdout)
        return 1

    try:
        tree = ast.parse(code, mode="exec")
        _validate_ast(tree)
    except Exception as exc:  # noqa: BLE001
        json.dump({"ok": False, "error": f"parse/validate: {exc}"}, sys.stdout)
        return 1

    safe_builtins = dict(_ALLOWED_BUILTINS)
    safe_builtins["__import__"] = _safe_import
    globals_dict: dict[str, Any] = {"__builtins__": safe_builtins}
    locals_dict: dict[str, Any] = {"inputs": inputs, "RESULT": None}

    try:
        exec(compile(tree, "<sandbox>", "exec"), globals_dict, locals_dict)  # noqa: S102
    except Exception as exc:  # noqa: BLE001
        json.dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sys.stdout)
        return 1

    result = locals_dict.get("RESULT", locals_dict.get("result"))
    try:
        json.dump({"ok": True, "result": result}, sys.stdout, default=str)
    except TypeError as exc:
        json.dump({"ok": False, "error": f"result not json-serializable: {exc}"}, sys.stdout)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
