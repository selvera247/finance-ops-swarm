# C4–C6 — Context budget · sanitize · self-heal

Thin craft layer on top of circuit breaker, HITL, sandbox, shadow, and memory.

## C4 Context budget

`pack_context` / tool `budget_pack_context(payload_json, kind, max_items, max_chars)`

- Caps list size and JSON char length for model context  
- Kinds: `payments` · `invoices` · `memory` · `generic` · `auto`  
- Env: `FINANCE_OPS_CTX_MAX_ITEMS` (8), `FINANCE_OPS_CTX_MAX_CHARS` (4000), `FINANCE_OPS_CTX_MAX_STR` (240)

## C5 Sanitize

`sanitize_for_export` redacts secrets (PATs, Slack tokens, Bearer, webhook URLs, secret-shaped keys) and long digit runs.

Wired into:

- `record_evidence` (all evidence JSON)  
- Slack HITL message text/blocks  
- MCP `_json` responses  

Preview tool: `sanitize_payload`.

## C6 Self-heal

`heal_result` / `run_with_heal`:

1. Classify: `transient` · `circuit_open` · `not_found` · `denied` · `error`  
2. Reset circuit on `circuit_open`  
3. Retry once when a `retry_fn` is supplied  
4. Else escalate `needs_review` with `resume_hint` — never invent balances  

Tools: `heal_tool_result` (classify only), `heal_suggest_payment` (live retry wrapper).

## Agent usage

```text
list_unmatched_payments → budget_pack_context
suggest fails → heal_suggest_payment
suspicious payload → sanitize_payload
```
