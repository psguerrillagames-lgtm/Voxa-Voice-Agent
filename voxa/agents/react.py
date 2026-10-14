"""ReAct loop: the model reasons, calls tools, observes results, repeats.

This is a hand-written loop rather than the SDK tool runner so the
orchestrator can see and trace every step, cap the step budget, and stream
the agent's interim thoughts to the dashboard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from voxa.llm import LLMClient
from voxa.observability import Tracer
from voxa.tools.base import Tool, run_tool


@dataclass
class AgentResult:
    agent: str
    text: str
    stop_reason: str
    steps: int
    tool_calls: list[dict] = field(default_factory=list)


def _text(content) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


async def run_react(llm: LLMClient, *, agent: str, system: str, task: str, tools: list[Tool],
                    tracer: Tracer, max_steps: int = 8) -> AgentResult:
    by_name = {t.name: t for t in tools}
    specs = [t.spec() for t in tools]
    messages: list[dict] = [{"role": "user", "content": task}]
    calls: list[dict] = []

    with tracer.span("agent", agent, agent=agent, task=task[:200]) as span:
        for step in range(1, max_steps + 1):
            response = await llm.create(agent=agent, system=system, messages=messages,
                                        tools=specs)
            # Append the full content (thinking blocks included) unchanged.
            messages.append({"role": "assistant", "content": response.content})
            if thought := _text(response.content):
                tracer.emit({"type": "thought", "agent": agent, "text": thought})

            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                span.data["steps"] = step
                return AgentResult(agent, _text(response.content), response.stop_reason,
                                   step, calls)

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool = by_name.get(block.name)
                if tool is None:
                    text, is_error = json.dumps({"error": f"no tool '{block.name}'"}), True
                else:
                    text, is_error = run_tool(tool, dict(block.input), tracer, agent=agent)
                calls.append({"tool": block.name, "args": dict(block.input), "error": is_error})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": text, "is_error": is_error})
            # All results for one turn go back in a single user message.
            messages.append({"role": "user", "content": results})

        span.data["steps"] = max_steps
        return AgentResult(agent, f"[{agent}] step limit reached; findings incomplete.",
                           "max_steps", max_steps, calls)
