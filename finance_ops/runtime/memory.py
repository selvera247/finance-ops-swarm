"""C2 — three-tier memory with automatic eviction.

Tiers
  working   — session scratch (small, short TTL, LRU)
  episodic  — turn / event memories (medium TTL, LRU)
  long_term — durable facts (large cap, LRU; ``pinned`` exempt)

All tiers persist under ``.warehouse/memory/<tier>.json``.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from data_plane.config import WAREHOUSE_DIR, ensure_dirs

Tier = Literal["working", "episodic", "long_term"]
TIERS: tuple[Tier, ...] = ("working", "episodic", "long_term")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.01, float(raw))
    except ValueError:
        return default


class MemoryLimits(BaseModel):
    max_items: int
    ttl_hours: float | None  # None = no TTL expiry


def default_limits() -> dict[Tier, MemoryLimits]:
    return {
        "working": MemoryLimits(
            max_items=_env_int("FINANCE_OPS_MEM_WORKING_MAX", 20),
            ttl_hours=_env_float("FINANCE_OPS_MEM_WORKING_TTL_H", 1.0),
        ),
        "episodic": MemoryLimits(
            max_items=_env_int("FINANCE_OPS_MEM_EPISODIC_MAX", 100),
            ttl_hours=_env_float("FINANCE_OPS_MEM_EPISODIC_TTL_H", 168.0),  # 7d
        ),
        "long_term": MemoryLimits(
            max_items=_env_int("FINANCE_OPS_MEM_LONG_MAX", 500),
            ttl_hours=None,  # size-only eviction unless overridden
        ),
    }


class MemoryItem(BaseModel):
    memory_id: str
    tier: Tier
    key: str
    value: Any
    session_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False
    created_at: str
    updated_at: str
    last_accessed_at: str
    access_count: int = 0


class MemoryStore:
    def __init__(self, root: Path | None = None, limits: dict[Tier, MemoryLimits] | None = None) -> None:
        ensure_dirs()
        self.root = root or (WAREHOUSE_DIR / "memory")
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = limits or default_limits()

    def _path(self, tier: Tier) -> Path:
        return self.root / f"{tier}.json"

    def _load(self, tier: Tier) -> list[MemoryItem]:
        path = self._path(tier)
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [MemoryItem.model_validate(row) for row in raw]

    def _save(self, tier: Tier, items: list[MemoryItem]) -> None:
        self._path(tier).write_text(
            json.dumps([i.model_dump() for i in items], indent=2, default=str),
            encoding="utf-8",
        )

    def _parse_ts(self, iso: str) -> datetime:
        return datetime.fromisoformat(iso)

    def _expired(self, item: MemoryItem, limits: MemoryLimits, now: datetime) -> bool:
        if item.pinned:
            return False
        if limits.ttl_hours is None:
            return False
        age = now - self._parse_ts(item.last_accessed_at)
        return age > timedelta(hours=limits.ttl_hours)

    def evict(self, tier: Tier | None = None) -> dict[str, Any]:
        """Drop TTL-expired then LRU overflow. Pinned items never evicted."""
        tiers: list[Tier] = [tier] if tier else list(TIERS)
        report: dict[str, Any] = {}
        now = _now()
        for t in tiers:
            limits = self.limits[t]
            items = self._load(t)
            before = len(items)
            kept = [i for i in items if not self._expired(i, limits, now)]
            ttl_dropped = before - len(kept)
            # LRU by last_accessed_at among unpinned
            if len(kept) > limits.max_items:
                pinned = [i for i in kept if i.pinned]
                unpinned = sorted(
                    [i for i in kept if not i.pinned],
                    key=lambda i: i.last_accessed_at,
                )
                overflow = len(kept) - limits.max_items
                # Prefer dropping oldest unpinned; never drop pinned even if over cap
                drop_n = min(overflow, len(unpinned))
                unpinned = unpinned[drop_n:]
                kept = pinned + unpinned
                lru_dropped = drop_n
            else:
                lru_dropped = 0
            self._save(t, kept)
            report[t] = {
                "before": before,
                "after": len(kept),
                "ttl_dropped": ttl_dropped,
                "lru_dropped": lru_dropped,
                "max_items": limits.max_items,
                "ttl_hours": limits.ttl_hours,
            }
        return report

    def put(
        self,
        *,
        tier: Tier,
        key: str,
        value: Any,
        session_id: str | None = None,
        tags: list[str] | None = None,
        pinned: bool = False,
    ) -> MemoryItem:
        if tier not in TIERS:
            raise ValueError(f"invalid tier: {tier}")
        key = key.strip()
        if not key:
            raise ValueError("key required")
        items = self._load(tier)
        now = _now_iso()
        existing = next((i for i in items if i.key == key and i.session_id == session_id), None)
        if existing:
            existing.value = value
            existing.tags = list(tags or existing.tags)
            existing.pinned = pinned or existing.pinned
            existing.updated_at = now
            existing.last_accessed_at = now
            item = existing
        else:
            item = MemoryItem(
                memory_id=f"MEM-{uuid.uuid4().hex[:10]}",
                tier=tier,
                key=key,
                value=value,
                session_id=session_id,
                tags=list(tags or []),
                pinned=pinned,
                created_at=now,
                updated_at=now,
                last_accessed_at=now,
            )
            items.append(item)
        self._save(tier, items)
        self.evict(tier)
        # Reload in case evicted (shouldn't if just written unless over cap and unpinned)
        refreshed = self.get(tier, key, session_id=session_id, touch=False)
        return refreshed or item

    def get(
        self,
        tier: Tier,
        key: str,
        *,
        session_id: str | None = None,
        touch: bool = True,
    ) -> MemoryItem | None:
        items = self._load(tier)
        item = next((i for i in items if i.key == key and i.session_id == session_id), None)
        if item is None and session_id is not None:
            # Fall back to session-less key in same tier
            item = next((i for i in items if i.key == key and i.session_id is None), None)
        if item is None:
            return None
        if touch:
            item.last_accessed_at = _now_iso()
            item.access_count += 1
            self._save(tier, items)
        return item

    def delete(self, tier: Tier, key: str, *, session_id: str | None = None) -> bool:
        items = self._load(tier)
        new_items = [i for i in items if not (i.key == key and i.session_id == session_id)]
        if len(new_items) == len(items):
            return False
        self._save(tier, new_items)
        return True

    def list(
        self,
        tier: Tier | None = None,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        tiers: list[Tier] = [tier] if tier else list(TIERS)
        out: list[MemoryItem] = []
        for t in tiers:
            for item in self._load(t):
                if session_id is not None and item.session_id not in {session_id, None}:
                    continue
                out.append(item)
        out.sort(key=lambda i: i.last_accessed_at, reverse=True)
        return out[: max(1, min(limit, 200))]

    def search(
        self,
        query: str,
        *,
        tier: Tier | None = None,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[MemoryItem]:
        q = (query or "").strip().lower()
        if not q:
            return []
        hits: list[tuple[int, MemoryItem]] = []
        for item in self.list(tier, session_id=session_id, limit=500):
            blob = " ".join(
                [
                    item.key,
                    json.dumps(item.value, default=str),
                    " ".join(item.tags),
                    item.session_id or "",
                ]
            ).lower()
            if q in blob:
                score = blob.count(q)
                hits.append((score, item))
        # Higher substring hit count first; then most recently accessed.
        hits.sort(key=lambda pair: (pair[0], pair[1].last_accessed_at), reverse=True)
        return [i for _, i in hits[: max(1, min(limit, 100))]]

    def promote(
        self,
        key: str,
        *,
        from_tier: Tier,
        to_tier: Tier,
        session_id: str | None = None,
        pinned: bool = False,
    ) -> MemoryItem:
        if from_tier == to_tier:
            raise ValueError("from_tier and to_tier must differ")
        order = {t: i for i, t in enumerate(TIERS)}
        if order[to_tier] < order[from_tier]:
            raise ValueError("can only promote upward: working → episodic → long_term")
        src = self.get(from_tier, key, session_id=session_id, touch=False)
        if src is None:
            raise KeyError(f"{from_tier}:{key}")
        dest_session = None if to_tier == "long_term" else session_id
        item = self.put(
            tier=to_tier,
            key=key,
            value=src.value,
            session_id=dest_session,
            tags=src.tags + [f"promoted_from:{from_tier}"],
            pinned=pinned or src.pinned,
        )
        self.delete(from_tier, key, session_id=session_id)
        return item

    def status(self) -> dict[str, Any]:
        self.evict()
        out: dict[str, Any] = {"tiers": {}, "root": str(self.root)}
        for t in TIERS:
            items = self._load(t)
            lim = self.limits[t]
            out["tiers"][t] = {
                "count": len(items),
                "pinned": sum(1 for i in items if i.pinned),
                "max_items": lim.max_items,
                "ttl_hours": lim.ttl_hours,
            }
        return out


DEFAULT_MEMORY = MemoryStore()
