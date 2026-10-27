# C7 — Sandboxed code exec (A + B + D + C)

Untrusted agent-written math/code returns **data only**. Mutations stay on typed
tools + HITL (`request_cash_app_approval` / `decide_approval`).

## Layers

| Layer | Mechanism |
| --- | --- |
| **A Calc** | AST-whitelisted expressions (`run_sandboxed_calc`) |
| **B Python** | Subprocess `python -I` + empty env + temp cwd + restricted builtins |
| **D Policy wall** | Blocklist scan; no `finance_ops` / write-tool names; result JSON only |
| **C Container** | Docker `run --network=none --read-only` (+ optional gVisor `runsc`) |

**Not in MCP** — read-only MCP stays warehouse reads; sandbox is an ADK agent tool.

## Agent tools

```text
run_sandboxed_calc(expression, inputs_json="{}")
run_sandboxed_python(code, inputs_json="{}")   # assign RESULT = ...
sandbox_status()                               # C7-C readiness
```

## Enable C7-C (container)

```powershell
# From repo root (Docker required)
bash scripts/build_sandbox_image.sh
$env:FINANCE_OPS_SANDBOX_ISOLATION = "container"   # or auto (default)
# Optional gVisor:
# $env:FINANCE_OPS_SANDBOX_RUNTIME = "runsc"
python -c "from finance_ops.tools.sandbox_tools import sandbox_status, run_sandboxed_python; print(sandbox_status()); print(run_sandboxed_python('RESULT = 1+1'))"
```

| Env | Default | Meaning |
| --- | --- | --- |
| `FINANCE_OPS_SANDBOX_ISOLATION` | `auto` | `subprocess` · `container` · `auto` (container if image+docker ok) |
| `FINANCE_OPS_SANDBOX_IMAGE` | `finance-ops-sandbox:latest` | Image tag |
| `FINANCE_OPS_SANDBOX_RUNTIME` | _(empty)_ | e.g. `runsc` for gVisor |
| `FINANCE_OPS_SANDBOX_MEM` | `256m` | Container memory |
| `FINANCE_OPS_SANDBOX_CPUS` | `0.5` | Container CPUs |
| `FINANCE_OPS_SANDBOX_TIMEOUT` | `2` | Guest timeout seconds |
| `FINANCE_OPS_SANDBOX_DOCKER` | `docker` | Docker CLI path |

Image: `infra/sandbox/Dockerfile` (worker only — no warehouse packages, no creds).

If container is requested but Docker/image is missing, **auto/container fall back** to subprocess and set `isolation_fallback`.

## Threat model

| Threat | B subprocess | C container |
| --- | --- | --- |
| `apply_payment_match` from guest | Blocked | Blocked |
| Read `.env` / ADC via `os` | Blocked in worker | No host mounts / empty env |
| Infinite loop | Timeout | Timeout + cgroup |
| Outbound HTTP | Not fully blocked | **`--network=none`** |
| Host escape | Not claimed | Stronger with gVisor (`runsc`) |
