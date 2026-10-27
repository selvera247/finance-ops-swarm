from __future__ import annotations

"""L4 policy vectors: Vertex embeddings / Vector Search with local hash fallback."""

import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from data_plane.config import VECTOR_DIR, ensure_dirs
from data_plane.vectors import vertex_embed as vx
from data_plane.warehouse import db

DIM = 64
INDEX_PATH = VECTOR_DIR / "policy_index.json"


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def hash_embed(text: str, dim: int = DIM) -> list[float]:
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        h = hash(tok)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _embed_documents(texts: list[str]) -> tuple[list[list[float]], str, int]:
    """Return embeddings, backend label, dim."""
    if vx.use_vertex_vectors():
        try:
            vectors = vx.vertex_embed_texts(texts)
            dim = len(vectors[0]) if vectors else 0
            return vectors, "vertex_text_embedding", dim
        except Exception:
            # Fall through to hash — demo-safe
            pass
    vectors = [hash_embed(t) for t in texts]
    return vectors, "local_hash", DIM


def _embed_query(text: str) -> tuple[list[float], str]:
    if vx.use_vertex_vectors():
        try:
            return vx.vertex_embed_query(text), "vertex_text_embedding"
        except Exception:
            pass
    return hash_embed(text), "local_hash"


def build_policy_index() -> dict[str, Any]:
    ensure_dirs()
    db.init_schema()
    docs = db.query_dicts("SELECT doc_id, title, text FROM policy_docs")
    texts = [f"{d['title']}\n{d['text']}" for d in docs]
    embeddings, backend, dim = _embed_documents(texts)
    items = []
    for doc, emb in zip(docs, embeddings):
        items.append(
            {
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "text": doc["text"],
                "embedding": emb,
            }
        )
    payload = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "dim": dim,
        "count": len(items),
        "items": items,
    }
    INDEX_PATH.write_text(json.dumps(payload), encoding="utf-8")
    # Matching Engine simulator (upsert shape)
    me_path = vx.upsert_local_matching_engine(items, dim=dim, backend=backend)
    run_id = f"vectors-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?,?,?)",
        [run_id, "vectors", "success", f"backend={backend};count={len(items)}", now, now],
    )
    return {
        "status": "success",
        "count": len(items),
        "path": str(INDEX_PATH),
        "matching_engine_sim": str(me_path),
        "backend": backend,
        "dim": dim,
        "run_id": run_id,
        "vertex": vx.vertex_status(),
    }


def search(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    top_k = max(1, min(int(top_k), 5))
    q, q_backend = _embed_query(query)

    # Prefer live Vector Search endpoint when configured
    if vx.use_vertex_vectors() and vx.vector_index_endpoint():
        try:
            neighbors = vx.matching_engine_find_neighbors(q, top_k=top_k)
            # Enrich from local catalog if present
            catalog = {}
            if INDEX_PATH.exists():
                for item in json.loads(INDEX_PATH.read_text(encoding="utf-8")).get("items", []):
                    catalog[item["doc_id"]] = item
            hits = []
            for n in neighbors:
                meta = catalog.get(n["doc_id"], {})
                hits.append(
                    {
                        "doc_id": n["doc_id"],
                        "title": meta.get("title"),
                        "snippet": (meta.get("text") or "")[:280],
                        "score": n["score"],
                        "backend": "vertex_vector_search",
                        "query_backend": q_backend,
                    }
                )
            if hits:
                return hits
        except Exception:
            pass

    # Local Matching Engine simulator
    hits = vx.query_local_matching_engine(q, top_k=top_k, cosine_fn=cosine)
    if hits:
        for h in hits:
            h["query_backend"] = q_backend
        return hits

    # Legacy index path
    if not INDEX_PATH.exists():
        build_policy_index()
        hits = vx.query_local_matching_engine(q, top_k=top_k, cosine_fn=cosine)
        if hits:
            for h in hits:
                h["query_backend"] = q_backend
            return hits

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    scored = []
    for item in index["items"]:
        scored.append(
            {
                "doc_id": item["doc_id"],
                "title": item["title"],
                "snippet": item["text"][:280],
                "score": round(cosine(q, item["embedding"]), 4),
                "backend": index.get("backend", "local_hash"),
                "query_backend": q_backend,
            }
        )
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:top_k]


def vertex_vector_status() -> dict[str, Any]:
    return vx.vertex_status()
