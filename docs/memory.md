# C2 — Three-tier memory + eviction

Persisted agent memory for multi-turn finance ops. Store under `.warehouse/memory/`.

## Tiers

| Tier | Purpose | Default cap | Default TTL |
| --- | --- | --- | --- |
| `working` | Session scratch | 20 | 1 hour |
| `episodic` | Turn / event notes | 100 | 7 days |
| `long_term` | Durable facts | 500 | none (size LRU only) |

**Eviction:** TTL expiry first, then LRU by `last_accessed_at`. **`pinned`** items are never evicted (may exceed cap).

## Tools

| Tool | Use |
| --- | --- |
| `memory_put(tier, key, value_json, session_id?, tags_csv?, pinned?)` | Upsert |
| `memory_get` / `memory_list` / `memory_search` | Read |
| `memory_promote(key, from_tier, to_tier, ...)` | working → episodic → long_term |
| `memory_evict` / `memory_status` | Ops |

## Env knobs

```text
FINANCE_OPS_MEM_WORKING_MAX=20
FINANCE_OPS_MEM_WORKING_TTL_H=1
FINANCE_OPS_MEM_EPISODIC_MAX=100
FINANCE_OPS_MEM_EPISODIC_TTL_H=168
FINANCE_OPS_MEM_LONG_MAX=500
```

## Cash-app pattern

1. After `suggest_payment_match`, `memory_put(working, "pay:PAY-1001", ...)`  
2. On human confirm, `memory_promote` → `episodic` or `long_term`  
3. Next session: `memory_search("PAY-1001")` before re-suggesting  

Memory does **not** apply matches — HITL remains the write path. Not exposed on read-only MCP.
