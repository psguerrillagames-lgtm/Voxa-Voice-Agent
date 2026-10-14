"""Tool definition shared by the agents, the guardrails and the MCP server."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from voxa.observability import Tracer


class Risk(StrEnum):
    READ = "read"  # no side effects; agents may call freely
    WRITE = "write"  # reversible change (restart, scale, config)
    DESTRUCTIVE = "destructive"  # changes what is running in prod (rollback)


class ToolError(Exception):
    """Raised by a tool for bad input; returned to the model as is_error."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., Any]
    risk: Risk = Risk.READ

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema}


def schema(required: dict[str, dict], optional: dict[str, dict] | None = None) -> dict:
    return {"type": "object", "properties": {**required, **(optional or {})},
            "required": list(required), "additionalProperties": False}


def run_tool(tool: Tool, args: dict, tracer: Tracer, agent: str = "") -> tuple[str, bool]:
    """Execute a tool and return (json_text, is_error). Never raises for tool faults."""
    with tracer.span("tool", tool.name, agent=agent, args=args, risk=tool.risk.value) as span:
        unknown = set(args) - set(tool.input_schema["properties"])
        missing = set(tool.input_schema["required"]) - set(args)
        if unknown or missing:
            span.error = f"bad args: unknown={sorted(unknown)} missing={sorted(missing)}"
            return json.dumps({"error": span.error}), True
        try:
            result = tool.fn(**args)
        except (ToolError, KeyError, ValueError, TypeError) as exc:
            span.error = str(exc)
            return json.dumps({"error": str(exc)}), True
        text = json.dumps(result, default=str)
        span.data["result_chars"] = len(text)
        return text, False
