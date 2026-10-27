from __future__ import annotations

from typing import Any


def extract_trajectory(events: list[Any]) -> dict[str, Any]:
    """Pull final text, agent authors, and tool names from ADK events."""
    agents: list[str] = []
    tools: list[str] = []
    final_chunks: list[str] = []

    for event in events:
        author = getattr(event, "author", None)
        if author and author not in agents:
            agents.append(author)

        for fc in event.get_function_calls() or []:
            name = getattr(fc, "name", None) or (
                fc.get("name") if isinstance(fc, dict) else None
            )
            if name and name not in tools:
                tools.append(name)

        content = getattr(event, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None) or []
        texts: list[str] = []
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                texts.append(text)
        if not texts:
            continue
        joined = "\n".join(texts)
        # Prefer final responses; keep last non-empty as fallback.
        if hasattr(event, "is_final_response") and event.is_final_response():
            final_chunks.append(joined)
        else:
            final_chunks.append(joined)

    final_text = final_chunks[-1] if final_chunks else ""
    return {
        "final_text": final_text,
        "agents_seen": agents,
        "tools_called": tools,
        "event_count": len(events),
    }
