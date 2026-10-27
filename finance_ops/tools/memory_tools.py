"""Agent tools for C2 three-tier memory."""

from __future__ import annotations

import json
from typing import Any, Literal

from finance_ops.lib.evidence import record_evidence
from finance_ops.runtime.circuit_breaker import DEFAULT_BREAKER
from finance_ops.runtime.memory import DEFAULT_MEMORY, TIERS, Tier


def _guard(tool_name: str) -> None:
    DEFAULT_BREAKER.record_tool(tool_name)


def _parse_value(value_json: str) -> Any:
    raw = (value_json or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _parse_tags(tags_csv: str) -> list[str]:
    return [t.strip() for t in (tags_csv or "").split(",") if t.strip()]


def _tier(tier: str) -> Tier:
    t = (tier or "").strip().lower()
    if t not in TIERS:
        raise ValueError(f"tier must be one of {list(TIERS)}")
    return t  # type: ignore[return-value]


def memory_put(
    tier: str,
    key: str,
    value_json: str,
    session_id: str = "",
    tags_csv: str = "",
    pinned: bool = False,
) -> dict[str, Any]:
    """Store a memory item. Tiers: working | episodic | long_term.

    value_json: JSON value or plain string. Eviction runs after write.
    """
    _guard("memory_put")
    try:
        item = DEFAULT_MEMORY.put(
            tier=_tier(tier),
            key=key,
            value=_parse_value(value_json),
            session_id=session_id.strip() or None,
            tags=_parse_tags(tags_csv),
            pinned=bool(pinned),
        )
        result: dict[str, Any] = {
            "status": "success",
            "item": item.model_dump(),
            "needs_review": False,
        }
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "error": str(exc), "needs_review": True}
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="memory_put",
        inputs={"tier": tier, "key": key, "session_id": session_id or None, "pinned": pinned},
        outputs={"status": result["status"], "memory_id": (result.get("item") or {}).get("memory_id")},
        sources=["memory:store"],
    )
    return result


def memory_get(tier: str, key: str, session_id: str = "") -> dict[str, Any]:
    """Fetch one memory by tier+key (updates LRU access time)."""
    _guard("memory_get")
    try:
        item = DEFAULT_MEMORY.get(_tier(tier), key, session_id=session_id.strip() or None)
        if item is None:
            result: dict[str, Any] = {
                "status": "not_found",
                "tier": tier,
                "key": key,
                "needs_review": False,
            }
        else:
            result = {"status": "success", "item": item.model_dump(), "needs_review": False}
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "error": str(exc), "needs_review": True}
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="memory_get",
        inputs={"tier": tier, "key": key, "session_id": session_id or None},
        outputs={"status": result["status"]},
        sources=["memory:store"],
    )
    return result


def memory_search(
    query: str,
    tier: str = "",
    session_id: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Substring search across key/value/tags. Empty tier searches all tiers."""
    _guard("memory_search")
    try:
        t = _tier(tier) if tier.strip() else None
        hits = DEFAULT_MEMORY.search(
            query,
            tier=t,
            session_id=session_id.strip() or None,
            limit=int(limit),
        )
        result: dict[str, Any] = {
            "status": "success",
            "count": len(hits),
            "items": [h.model_dump() for h in hits],
            "needs_review": False,
        }
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "error": str(exc), "needs_review": True}
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="memory_search",
        inputs={"query": query, "tier": tier or None, "session_id": session_id or None},
        outputs={"count": result.get("count", 0)},
        sources=["memory:store"],
    )
    return result


def memory_list(tier: str = "", session_id: str = "", limit: int = 50) -> dict[str, Any]:
    """List recent memories (all tiers if tier blank)."""
    _guard("memory_list")
    try:
        t = _tier(tier) if tier.strip() else None
        items = DEFAULT_MEMORY.list(t, session_id=session_id.strip() or None, limit=int(limit))
        result: dict[str, Any] = {
            "status": "success",
            "count": len(items),
            "items": [i.model_dump() for i in items],
            "needs_review": False,
        }
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "error": str(exc), "needs_review": True}
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="memory_list",
        inputs={"tier": tier or None, "session_id": session_id or None},
        outputs={"count": result.get("count", 0)},
        sources=["memory:store"],
    )
    return result


def memory_promote(
    key: str,
    from_tier: str,
    to_tier: str,
    session_id: str = "",
    pinned: bool = False,
) -> dict[str, Any]:
    """Promote working → episodic → long_term (copies then deletes source)."""
    _guard("memory_promote")
    try:
        item = DEFAULT_MEMORY.promote(
            key,
            from_tier=_tier(from_tier),
            to_tier=_tier(to_tier),
            session_id=session_id.strip() or None,
            pinned=bool(pinned),
        )
        result: dict[str, Any] = {
            "status": "success",
            "item": item.model_dump(),
            "needs_review": False,
        }
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "error": str(exc), "needs_review": True}
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="memory_promote",
        inputs={
            "key": key,
            "from_tier": from_tier,
            "to_tier": to_tier,
            "session_id": session_id or None,
        },
        outputs={"status": result["status"]},
        sources=["memory:store"],
    )
    return result


def memory_evict(tier: str = "") -> dict[str, Any]:
    """Run TTL + LRU eviction now (also runs automatically on put)."""
    _guard("memory_evict")
    try:
        t = _tier(tier) if tier.strip() else None
        report = DEFAULT_MEMORY.evict(t)
        result: dict[str, Any] = {
            "status": "success",
            "report": report,
            "needs_review": False,
        }
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "error": str(exc), "needs_review": True}
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="memory_evict",
        inputs={"tier": tier or None},
        outputs={"status": result["status"]},
        sources=["memory:store"],
    )
    return result


def memory_status() -> dict[str, Any]:
    """Counts and caps per tier after a refresh eviction pass."""
    _guard("memory_status")
    snap = DEFAULT_MEMORY.status()
    result = {"status": "success", "memory": snap, "needs_review": False}
    result["evidence"] = record_evidence(
        agent="coordinator",
        action="memory_status",
        inputs={},
        outputs={"tiers": {k: v.get("count") for k, v in snap.get("tiers", {}).items()}},
        sources=["memory:store"],
    )
    return result
