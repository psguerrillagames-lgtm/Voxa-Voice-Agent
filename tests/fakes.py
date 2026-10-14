"""Scripted stand-in for ClaudeLLM so agent logic is testable offline."""

from __future__ import annotations

import itertools
from types import SimpleNamespace


def text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


_ids = itertools.count(1)


def tool_use(name: str, **args) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"toolu_{next(_ids)}", name=name, input=args)


def reply(*blocks, stop: str | None = None) -> SimpleNamespace:
    if stop is None:
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


class FakeLLM:
    """Replays scripted replies per agent name; parse() returns queued objects."""

    def __init__(self, scripts: dict[str, list] | None = None,
                 parsed: dict[str, list] | None = None):
        self.scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self.parsed = {k: list(v) for k, v in (parsed or {}).items()}
        self.calls: list[dict] = []

    async def create(self, *, agent, system, messages, tools=None, max_tokens=16000):
        self.calls.append({"agent": agent, "messages": list(messages), "tools": tools})
        return self.scripts[agent].pop(0)

    async def parse(self, *, agent, system, messages, output_format, max_tokens=16000):
        self.calls.append({"agent": agent, "messages": list(messages), "system": system})
        return self.parsed[agent].pop(0)
