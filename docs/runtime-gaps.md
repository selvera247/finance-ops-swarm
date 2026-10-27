# Runtime gaps closed (Agent Engineer checklist)

In-repo implementations for the highest-priority production primitives.

| # | Gap | Module / surface |
| --- | --- | --- |
| 11 | Fallback router | `finance_ops/runtime/fallback_router.py` → tool `resolve_portal_with_fallback` |
| 12 | Circuit breaker | `finance_ops/runtime/circuit_breaker.py` → `circuit_status` / tool guards |
| 8 | HITL | `finance_ops/runtime/hitl.py` + `hitl_server.py` (:8787) → `request_approval` / `decide_approval` |
| 1 | Durability | `finance_ops/runtime/durable.py` (file checkpoints) → `start_durable_reconcile` / `scripts/run_durable_workflow.py` |
| 5 | Typed A2A | `finance_ops/runtime/a2a.py` → `run_typed_a2a_aging` |
| 10 | CI gate | `.github/workflows/ci.yml` — pytest + L2 trajectory `--dry-run` |

## Fallback router (#11)

Order: optional API lookup → warehouse `portal_extracts` → Playwright GUI pull
(legacy bank mock only). Returns `path` ∈ `{api, warehouse, browser, none}`.

## Circuit breaker (#12)

Process-wide `DEFAULT_BREAKER` caps tool calls (25) and nest depth (8).
GUI / runtime tools call `record_tool`; open circuit returns `circuit_open`.

## HITL (#8)

`ApprovalStore` serializes `PendingApproval` under `.warehouse/hitl/`.
Local Slack stand-in:

```bash
PYTHONPATH=. python -m finance_ops.runtime.hitl_server
# open http://127.0.0.1:8787/  or POST /api/decide
```

## Durable DAG (#1)

File-checkpointed state machine (Temporal/LangGraph-shaped, no external cluster):

```bash
PYTHONPATH=. python scripts/run_durable_workflow.py --no-browser
PYTHONPATH=. python scripts/run_durable_workflow.py --resume WF-...
```

Steps: `batch_ingest` → `process_incoming` → `resolve_portal` → `reconcile_smoke`.

## Typed A2A (#5)

`AgentTask` / `AgentResult` / `SwarmState` Pydantic models. Coordinator builds a
typed task; invoice specialist returns a typed result with evidence refs.

## CI (#10)

GitHub Actions runs `pytest -q` then
`python evals/run_trajectory_eval.py --dry-run --min-pass-rate 0.8`.
Fail the job on regression.
