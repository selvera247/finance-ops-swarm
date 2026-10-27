from __future__ import annotations

from typing import Any

from data_plane.vectors import embed
from finance_ops.lib.evidence import record_evidence


def search_policies(query: str, top_k: int = 3) -> dict[str, Any]:
    top_k = max(1, min(int(top_k), 5))
    hits = embed.search(query, top_k=top_k)
    result = {
        "status": "success", "query": query, "hits": hits,
        "backend": embed.vertex_vector_status(), "needs_review": len(hits) == 0,
    }
    result["evidence"] = record_evidence(
        agent="coordinator", action="search_policies",
        inputs={"query": query, "top_k": top_k},
        outputs={"hit_ids": [h["doc_id"] for h in hits]},
        sources=[f"vector_index:{h['doc_id']}" for h in hits],
    )
    return result
