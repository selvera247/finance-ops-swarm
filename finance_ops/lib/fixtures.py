from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from finance_ops.lib.paths import DATA_DIR


@lru_cache(maxsize=None)
def _load_json(name: str) -> Any:
    with (DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def invoices() -> list[dict[str, Any]]:
    return list(_load_json("invoices.json"))


def payments() -> list[dict[str, Any]]:
    return list(_load_json("payments.json"))


def contracts() -> list[dict[str, Any]]:
    return list(_load_json("contracts.json"))


def knowledge_graph() -> dict[str, Any]:
    return dict(_load_json("knowledge_graph.json"))


def rag_corpus() -> list[dict[str, Any]]:
    return list(_load_json("rag_corpus.json"))


def reload_fixtures() -> None:
    _load_json.cache_clear()
