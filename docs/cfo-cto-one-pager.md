# Finance Ops Agents — CFO / CTO one-pager

**Audience:** CFO (control & risk) · CTO / Head of Data (architecture) · PSO interview panel  
**Status:** Master plan complete · Spike A + craft C1/C2/C3/C7 · Slack HITL + **live Cloud Run**  
**Date:** 2026-10-21  
**Live API:** https://finance-ops-301858971164.us-central1.run.app/docs  
**Backlog:** [backlog.md](backlog.md)

---

## 60-second talk track

> “We don’t put a chatbot on PDFs. We put specialists on a **warehouse**, with **evidence** on every material call, a **human gate** for write-offs (Slack Approve/Reject), and a **GUI fallback** when the bank has no API. Same contracts run locally and on **Cloud Run**. Cash-app exceptions can be **shadowed** safely, scored with a **sandbox**, and remembered across turns — apply still requires a human.”

---

## The problem (30 seconds)

AR exceptions, unmatched cash, and legacy portals still burn analyst hours. Most “AI for finance” demos are chat over PDFs. **The gap is governed Data → AI**: agents on a warehouse, with evidence, human gates, and a path when APIs do not exist.

## What we built (demo you can run)

| Layer | Live today |
| --- | --- |
| Data plane | DuckDB · BigQuery mode (L3; live load proven) |
| Portal unlock | Playwright mock bank + CSV drop zones |
| Agents | ADK coordinator + invoice / payments / contracts / reconciliation |
| Governance | `evidence_id` · write-offs → `needs_review` · Slack HITL |
| Runtime | Fallback · breaker · durable DAG · typed A2A · **sandbox** · **shadow** · **memory** |
| IDE surface | Read-only MCP (`finance_ops_readonly`) |
| Cloud | **Cloud Run** FastAPI (`/health`, `/v1/aging`, `/v1/bootstrap`) |
| AgentOps | pytest + L2 trajectory dry-run CI |
| Narrative | This one-pager (L7) |

**Validated live:**

- Aging `CUST-ACME` → **$16,700** (ADK + Cloud Run)
- Spike A cash app: suggest → HITL approve → apply (`PAY-1001` → `INV-84219`)
- Parking lot proven then torn down for idle cost: BigQuery · Matching Engine · Spanner · Agent Engine (reactivate runbooks in-repo)
- MCP: Cursor calls warehouse tools read-only

## Architecture (one picture)

```text
ERP JSON + portal CSVs / GUI
        → warehouse (DuckDB · BigQuery when configured)
        → features / KG / RAG
        → ADK multi-agent + evidence + memory
        → sandbox calc · shadow trajectories (no side effects)
        → Slack HITL / circuit / durable resume
        → Cloud Run HTTP API (live) · MCP read gateway (IDE)
```

## CFO answers

| Question | Answer |
| --- | --- |
| Can it silently write off cash? | **No.** Write-offs flag `needs_review` and open a Slack approval. |
| Audit trail? | Yes — `.evidence/EVD-*.json` + HITL `APPR-*.json` + shadow `SHD-*`. |
| Who owns the decision? | Human for money movement; agent recommends with cited sources. |
| What’s the control story? | Circuit breaker; expiring approvals; sandbox policy wall; shadow before apply. |

## CTO answers

| Question | Answer |
| --- | --- |
| Why not “just an LLM”? | Tools read a **data plane**; specialists are routable; RAG/KG/MCP are pluggable. |
| No API on the bank? | **Fallback router:** API → warehouse → Playwright GUI extract. |
| Production path? | Cloud Run URL live; BigQuery mode + Slack webhook + Terraform. |
| How do we prevent regressions? | CI: unit tests + trajectory dry-run pass-rate gate. |

## Trade-offs we own

- Local DuckDB latency vs BigQuery freshness (mode switch, not rewrite).
- Local / Vertex-shaped vectors vs full Matching Engine (idle-cost teardown; reactivate for demos).
- Auto-match score vs human review cost (`needs_review` threshold).
- File-checkpoint durable DAG vs managed Temporal.
- Subprocess sandbox (A+B+D) vs container jail (C7-C) for untrusted code.
- Slack link buttons need a reachable HITL URL (localhost desktop; ngrok for phone).

## Done vs next

| Done | Next (see [backlog.md](backlog.md)) |
| --- | --- |
| Master plan L3–L6 · Cloud Run · Slack HITL | **Spike B** portal extract (or deepen Spike A BQ/Slack) |
| Parking lot proven + idle teardown runbooks | Craft **C4–C6** (context · sanitize · self-heal); optional **C7-C** |
| Spike A · MCP · sandbox · shadow · memory | Hygiene: branch cleanup · revoke PATs · delete idle Agent Engine |

## Ask / next conversation

With Spike A + craft baseline in place, pick: **Spike B portal extract** for one carrier/payer, or **C4–C6** hardening. Production still means a real AR exception queue — evidence + HITL stay non-negotiable.

---

*Repo: `selvera247/finance_agents` · Status: [master-plan-status.md](master-plan-status.md) · Backlog: [backlog.md](backlog.md)*
