from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from finance_ops.runtime.memory import MemoryLimits, MemoryStore
from finance_ops.tools.memory_tools import (
    memory_get,
    memory_promote,
    memory_put,
    memory_search,
    memory_status,
)


def test_put_get_promote(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    item = store.put(
        tier="working",
        key="pay:PAY-1001",
        value={"recommendation": "INV-84219"},
        session_id="sess-1",
        tags=["cash_app"],
    )
    assert item.memory_id.startswith("MEM-")
    got = store.get("working", "pay:PAY-1001", session_id="sess-1")
    assert got is not None
    assert got.value["recommendation"] == "INV-84219"

    promoted = store.promote(
        "pay:PAY-1001",
        from_tier="working",
        to_tier="episodic",
        session_id="sess-1",
    )
    assert promoted.tier == "episodic"
    assert store.get("working", "pay:PAY-1001", session_id="sess-1") is None
    assert store.get("episodic", "pay:PAY-1001", session_id="sess-1") is not None


def test_lru_eviction(tmp_path: Path) -> None:
    limits = {
        "working": MemoryLimits(max_items=3, ttl_hours=24),
        "episodic": MemoryLimits(max_items=10, ttl_hours=24),
        "long_term": MemoryLimits(max_items=10, ttl_hours=None),
    }
    store = MemoryStore(root=tmp_path / "memory", limits=limits)
    for i in range(5):
        store.put(tier="working", key=f"k{i}", value=i)
    status = store.status()
    assert status["tiers"]["working"]["count"] == 3
    keys = {i.key for i in store.list("working", limit=10)}
    assert keys == {"k2", "k3", "k4"}


def test_pinned_survives_eviction(tmp_path: Path) -> None:
    limits = {
        "working": MemoryLimits(max_items=2, ttl_hours=24),
        "episodic": MemoryLimits(max_items=10, ttl_hours=24),
        "long_term": MemoryLimits(max_items=10, ttl_hours=None),
    }
    store = MemoryStore(root=tmp_path / "memory", limits=limits)
    store.put(tier="working", key="pin-me", value=1, pinned=True)
    store.put(tier="working", key="a", value=2)
    store.put(tier="working", key="b", value=3)
    store.put(tier="working", key="c", value=4)
    keys = {i.key for i in store.list("working", limit=20)}
    assert "pin-me" in keys


def test_ttl_eviction(tmp_path: Path) -> None:
    limits = {
        "working": MemoryLimits(max_items=20, ttl_hours=1),
        "episodic": MemoryLimits(max_items=20, ttl_hours=1),
        "long_term": MemoryLimits(max_items=20, ttl_hours=None),
    }
    store = MemoryStore(root=tmp_path / "memory", limits=limits)
    item = store.put(tier="working", key="old", value=1)
    # Backdate access time
    items = store._load("working")
    items[0].last_accessed_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    store._save("working", items)
    report = store.evict("working")
    assert report["working"]["ttl_dropped"] == 1
    assert store.get("working", "old", touch=False) is None
    assert item.key == "old"


def test_tool_wrappers(tmp_path: Path, monkeypatch) -> None:
    from finance_ops.tools import memory_tools as mt

    store = MemoryStore(root=tmp_path / "memory")
    monkeypatch.setattr(mt, "DEFAULT_MEMORY", store)

    put = memory_put("working", "cust:C-1042", '{"note":"partial remittance"}', "s1", "ar")
    assert put["status"] == "success"
    got = memory_get("working", "cust:C-1042", "s1")
    assert got["status"] == "success"
    assert got["item"]["value"]["note"] == "partial remittance"
    hits = memory_search("partial", "working", "s1")
    assert hits["count"] >= 1
    promo = memory_promote("cust:C-1042", "working", "long_term", "s1", True)
    assert promo["status"] == "success"
    assert promo["item"]["tier"] == "long_term"
    assert promo["item"]["pinned"] is True
    st = memory_status()
    assert st["memory"]["tiers"]["long_term"]["count"] >= 1
