"""Lightweight tracing: every LLM call, tool call and agent step becomes a span.

Spans feed the live dashboard (via subscribers) and the eval reports
(latency, token usage and dollar cost per incident).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

# USD per million tokens (input, output) for cost estimates.
PRICING = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclass
class Span:
    kind: str  # llm | tool | agent | voice | action
    name: str
    agent: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    start: float = field(default_factory=time.perf_counter)
    ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Tracer:
    def __init__(self) -> None:
        self.spans: list[Span] = []
        self._subscribers: list[Callable[[dict], None]] = []

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        self._subscribers.append(fn)

    def emit(self, event: dict) -> None:
        for fn in self._subscribers:
            fn(event)

    @contextmanager
    def span(self, kind: str, name: str, agent: str = "", **data: Any):
        span = Span(kind, name, agent, data=dict(data))
        self.emit({"type": "span_start", "kind": kind, "name": name, "agent": agent,
                   "id": span.id, "data": span.data})
        try:
            yield span
        except Exception as exc:
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span.ms = round((time.perf_counter() - span.start) * 1000, 1)
            self.spans.append(span)
            event = asdict(span)
            event.pop("start")
            self.emit({"type": "span_end", **event})

    def summary(self, model: str = "claude-opus-5-5") -> dict:
        llm = [s for s in self.spans if s.kind == "llm"]
        tin = sum(s.input_tokens for s in llm)
        tout = sum(s.output_tokens for s in llm)
        pin, pout = PRICING.get(model, (0.0, 0.0))
        return {
            "llm_calls": len(llm),
            "tool_calls": sum(1 for s in self.spans if s.kind == "tool"),
            "input_tokens": tin,
            "output_tokens": tout,
            "cost_usd": round(tin / 1e6 * pin + tout / 1e6 * pout, 4),
            "llm_ms": round(sum(s.ms for s in llm), 1),
        }
