"""L4 Vertex AI text embeddings + Vector Search client.

When credentials / flags are missing, callers fall back to local hash embeddings
and a file-backed Matching Engine simulator (same query contract).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_plane.config import VECTOR_DIR, ensure_dirs, gcp_project


def use_vertex_vectors() -> bool:
    return os.getenv("FINANCE_OPS_USE_VERTEX_VECTORS", "").lower() in {"1", "true", "yes"}


def vertex_location() -> str:
    return os.getenv("FINANCE_OPS_VERTEX_LOCATION", "us-central1")


def vertex_embedding_model() -> str:
    return os.getenv(
        "FINANCE_OPS_EMBEDDING_MODEL",
        "text-embedding-004",
    )


def vector_index_endpoint() -> str | None:
    return os.getenv("FINANCE_OPS_VECTOR_INDEX_ENDPOINT") or None


def vertex_embed_texts(texts: list[str]) -> list[list[float]]:
    """Call Vertex text embedding API. Raises on misconfig/errors."""
    project = gcp_project()
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT required for Vertex embeddings")
    try:
        from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel
        import vertexai
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("google-cloud-aiplatform not installed") from exc

    vertexai.init(project=project, location=vertex_location())
    model = TextEmbeddingModel.from_pretrained(vertex_embedding_model())
    inputs = [TextEmbeddingInput(text=t, task_type="RETRIEVAL_DOCUMENT") for t in texts]
    # Batch in chunks of 16 (API-friendly)
    out: list[list[float]] = []
    for i in range(0, len(inputs), 16):
        chunk = inputs[i : i + 16]
        embeddings = model.get_embeddings(chunk)
        out.extend([list(e.values) for e in embeddings])
    return out


def vertex_embed_query(text: str) -> list[float]:
    project = gcp_project()
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT required for Vertex embeddings")
    try:
        from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel
        import vertexai
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("google-cloud-aiplatform not installed") from exc

    vertexai.init(project=project, location=vertex_location())
    model = TextEmbeddingModel.from_pretrained(vertex_embedding_model())
    emb = model.get_embeddings(
        [TextEmbeddingInput(text=text, task_type="RETRIEVAL_QUERY")]
    )[0]
    return list(emb.values)


def matching_engine_find_neighbors(
    query_embedding: list[float],
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Query a deployed Vertex Vector Search index endpoint (Matching Engine)."""
    endpoint = vector_index_endpoint()
    project = gcp_project()
    if not endpoint or not project:
        raise RuntimeError("FINANCE_OPS_VECTOR_INDEX_ENDPOINT and project required")

    try:
        from google.cloud import aiplatform
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("google-cloud-aiplatform not installed") from exc

    aiplatform.init(project=project, location=vertex_location())
    index_endpoint = aiplatform.MatchingEngineIndexEndpoint(index_endpoint_name=endpoint)
    deployed = os.getenv("FINANCE_OPS_VECTOR_DEPLOYED_INDEX_ID", "finance_ops_policies")
    response = index_endpoint.find_neighbors(
        deployed_index_id=deployed,
        queries=[query_embedding],
        num_neighbors=top_k,
    )
    hits: list[dict[str, Any]] = []
    for neighbor in response[0]:
        hits.append(
            {
                "doc_id": neighbor.id,
                "score": float(neighbor.distance) if neighbor.distance is not None else 0.0,
                "backend": "vertex_vector_search",
            }
        )
    return hits


def local_me_path() -> Path:
    ensure_dirs()
    return VECTOR_DIR / "matching_engine_sim.json"


def upsert_local_matching_engine(items: list[dict[str, Any]], *, dim: int, backend: str) -> Path:
    """File-backed Matching Engine simulator (same upsert/query shape as ME)."""
    path = local_me_path()
    payload = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "dim": dim,
        "count": len(items),
        "items": items,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def query_local_matching_engine(
    query_embedding: list[float],
    *,
    top_k: int = 3,
    cosine_fn,
) -> list[dict[str, Any]]:
    path = local_me_path()
    if not path.exists():
        return []
    index = json.loads(path.read_text(encoding="utf-8"))
    scored = []
    for item in index.get("items") or []:
        scored.append(
            {
                "doc_id": item["doc_id"],
                "title": item.get("title"),
                "snippet": (item.get("text") or "")[:280],
                "score": round(cosine_fn(query_embedding, item["embedding"]), 4),
                "backend": index.get("backend", "local_me_sim"),
            }
        )
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[: max(1, min(top_k, 10))]


def vertex_status() -> dict[str, Any]:
    enabled = use_vertex_vectors()
    project = gcp_project()
    status: dict[str, Any] = {
        "enabled": enabled,
        "project": project,
        "location": vertex_location(),
        "embedding_model": vertex_embedding_model(),
        "index_endpoint": vector_index_endpoint(),
        "local_me_sim": local_me_path().exists(),
    }
    if not enabled:
        status["active_backend"] = "local_hash"
        status["note"] = "Set FINANCE_OPS_USE_VERTEX_VECTORS=true for Vertex path"
        return status
    if not project:
        status["active_backend"] = "local_me_sim"
        status["ok"] = False
        status["reason"] = "GOOGLE_CLOUD_PROJECT unset — using local ME simulator"
        return status
    try:
        import google.cloud.aiplatform  # noqa: F401

        status["sdk"] = "google-cloud-aiplatform"
        status["ok"] = True
        status["active_backend"] = (
            "vertex_vector_search" if vector_index_endpoint() else "vertex_embed_local_me"
        )
    except ImportError:
        status["ok"] = False
        status["active_backend"] = "local_hash"
        status["reason"] = "google-cloud-aiplatform not installed"
    return status
