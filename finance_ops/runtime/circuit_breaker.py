"""#12 Agentic circuit breaker — halt runaway tool/loop recursion."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


class CircuitOpenError(RuntimeError):
    """Raised when loop depth or tool-call budget is exhausted."""


@dataclass
class CircuitBreaker:
    max_tool_calls: int = 25
    max_depth: int = 8
    window_seconds: float = 300.0
    _tool_calls: int = 0
    _depth: int = 0
    _opened_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _events: list[dict[str, Any]] = field(default_factory=list)

    def reset(self) -> None:
        with self._lock:
            self._tool_calls = 0
            self._depth = 0
            self._opened_at = None
            self._events.clear()

    def enter(self, label: str = "invoke") -> None:
        with self._lock:
            self._depth += 1
            self._events.append({"ts": time.time(), "op": "enter", "label": label, "depth": self._depth})
            if self._depth > self.max_depth:
                self._opened_at = time.time()
                raise CircuitOpenError(
                    f"circuit open: depth {self._depth} > max_depth {self.max_depth}"
                )

    def exit(self, label: str = "invoke") -> None:
        with self._lock:
            self._depth = max(0, self._depth - 1)
            self._events.append({"ts": time.time(), "op": "exit", "label": label, "depth": self._depth})

    def record_tool(self, tool_name: str) -> None:
        with self._lock:
            self._tool_calls += 1
            self._events.append(
                {
                    "ts": time.time(),
                    "op": "tool",
                    "tool": tool_name,
                    "tool_calls": self._tool_calls,
                }
            )
            if self._tool_calls > self.max_tool_calls:
                self._opened_at = time.time()
                raise CircuitOpenError(
                    f"circuit open: tool_calls {self._tool_calls} > max {self.max_tool_calls} "
                    f"(last={tool_name})"
                )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tool_calls": self._tool_calls,
                "depth": self._depth,
                "max_tool_calls": self.max_tool_calls,
                "max_depth": self.max_depth,
                "open": self._opened_at is not None,
                "opened_at": self._opened_at,
                "recent_events": self._events[-20:],
            }


# Process-wide default breaker for tool wrappers
DEFAULT_BREAKER = CircuitBreaker()
