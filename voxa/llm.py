"""Thin async wrapper over the Anthropic Messages API.

Every call goes through here so we get one place for: model + effort defaults,
server-side refusal fallbacks, token accounting and tracing. Tests swap in a
scripted fake with the same two methods.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from voxa.config import settings
from voxa.observability import Tracer

T = TypeVar("T", bound=BaseModel)

# Server-side fallback: if the primary model declines, the API re-runs the
# request on a suitable model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMClient(Protocol):
    async def create(self, *, agent: str, system: str, messages: list,
                     tools: list[dict] | None = None, max_tokens: int = 16000) -> Any: ...

    async def parse(self, *, agent: str, system: str, messages: list,
                    output_format: type[T], max_tokens: int = 16000) -> T: ...


class ClaudeLLM:
    def __init__(self, tracer: Tracer, model: str = settings.model,
                 effort: str = settings.effort, client: AsyncAnthropic | None = None):
        self.client = client or AsyncAnthropic()
        self.tracer = tracer
        self.model = model
        self.effort = effort

    def _common(self, system: str, messages: list, max_tokens: int) -> dict:
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }

    async def create(self, *, agent: str, system: str, messages: list,
                     tools: list[dict] | None = None, max_tokens: int = 16000) -> Any:
        kwargs = self._common(system, messages, max_tokens)
        if tools:
            kwargs["tools"] = tools
        with self.tracer.span("llm", "messages.create", agent=agent) as span:
            response = await self.client.beta.messages.create(**kwargs)
            span.input_tokens = response.usage.input_tokens
            span.output_tokens = response.usage.output_tokens
            span.data["stop_reason"] = response.stop_reason
        return response

    async def parse(self, *, agent: str, system: str, messages: list,
                    output_format: type[T], max_tokens: int = 16000) -> T:
        kwargs = self._common(system, messages, max_tokens)
        with self.tracer.span("llm", f"parse:{output_format.__name__}", agent=agent) as span:
            response = await self.client.beta.messages.parse(output_format=output_format,
                                                             **kwargs)
            span.input_tokens = response.usage.input_tokens
            span.output_tokens = response.usage.output_tokens
            span.data["stop_reason"] = response.stop_reason
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"{agent}: no structured output (stop={response.stop_reason})")
        return response.parsed_output
