# Backlog (post master plan + parking lot)

**As of:** 2026-10-21  

Portfolio craft + spikes are complete. Remaining items are hygiene and the next product step (real AR exception queue).

## Production spikes

| Item | Status |
| --- | --- |
| Spike A sample + loader + HITL apply | **Done** |
| Spike A Slack webhook (HITL notify + approve) | **Done** (validated locally) — [optional-spike-a-ops.md](optional-spike-a-ops.md) |
| Spike A BigQuery load | **Done** (validated; `PAY-1001`/`2001`/`3001` in BQ) — [optional-spike-a-ops.md](optional-spike-a-ops.md) |
| Spike A BQ loader hardening (`received_at` + streaming buffer) | **Done** — merged PR #21 |
| **Spike B portal extract** | **Done** — `data/spike_b` · `scripts/load_spike_b.py` |

## Agent Engineer craft

| ID | Item | Status |
| --- | --- | --- |
| **C1** | **Read-only MCP** | **Done** — `python -m finance_ops.mcp` · [mcp.md](mcp.md) |
| **C7** | **Sandbox A+B+D+C** | **Done** — [sandbox.md](sandbox.md) |
| **C3** | **Shadow trajectories** | **Done** — [shadow-trajectories.md](shadow-trajectories.md) |
| **C2** | **3-tier memory + eviction** | **Done** — [memory.md](memory.md) |
| **C4–C6** | **Context budget · sanitize · self-heal** | **Done** — [craft-c4-c6.md](craft-c4-c6.md) |

## Hygiene

| Item | Status |
| --- | --- |
| Revoke chat-exposed PATs | **Ongoing** |
| Delete merged `cursor/*` remotes | **Done** (re-clean after each merge) |
| Delete `cursor/bq-spike-a-received-at-a24d` | Optional |
| Slack `.env` load | **Done** |
| One-pager refresh | Optional (status/next section lags Spike B + C4–C7) |
| Drop `cursor/backlog-a24d` | **Done** |
| Delete idle Agent Engine | **Done** |
| Bootstrap sqlite | Live via `/v1/bootstrap` |

## Next (not scheduled)

| Item | Notes |
| --- | --- |
| Real AR exception queue | Production path beyond spikes — feed, triage, HITL, apply back to ERP/warehouse |
