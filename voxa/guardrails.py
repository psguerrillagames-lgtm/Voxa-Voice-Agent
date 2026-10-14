"""Policy layer between the agents and anything that changes production.

- Agents investigating an incident only get READ tools (least privilege).
- Any WRITE or DESTRUCTIVE action needs explicit human approval.
- Dry-run mode records what would have happened without touching infra.
- Every decision lands in an append-only audit log.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from voxa.observability import Tracer
from voxa.tools.base import Risk, Tool, run_tool

Approver = Callable[["ActionRequest"], Awaitable[bool]]


@dataclass
class ActionRequest:
    tool: str
    args: dict
    risk: Risk
    reason: str


@dataclass
class ActionOutcome:
    status: str  # executed | dry_run | denied | blocked | failed
    result: dict | None = None
    detail: str = ""


@dataclass
class Policy:
    tools: dict[str, Tool]
    dry_run: bool = True
    # Services the agent may touch at all; anything else is refused outright.
    allowed_services: frozenset[str] = frozenset(
        {"api-gateway", "checkout", "payments", "inventory", "recommendations"})
    max_replicas: int = 20
    audit: list[dict] = field(default_factory=list)

    def check(self, req: ActionRequest) -> str | None:
        """Return a reason to block, or None if the request is allowed to go to approval."""
        if req.tool not in self.tools:
            return f"tool '{req.tool}' is not an allowed action"
        service = req.args.get("service")
        if service not in self.allowed_services:
            return f"service '{service}' is outside the allowlist"
        if req.tool == "scale_service" and req.args.get("replicas", 0) > self.max_replicas:
            return f"replicas above limit {self.max_replicas}"
        return None

    async def execute(self, req: ActionRequest, approver: Approver,
                      tracer: Tracer) -> ActionOutcome:
        outcome = await self._execute(req, approver, tracer)
        self.audit.append({"at": time.time(), "tool": req.tool, "args": req.args,
                           "risk": req.risk.value, "reason": req.reason,
                           "status": outcome.status, "detail": outcome.detail})
        return outcome

    async def _execute(self, req: ActionRequest, approver: Approver,
                       tracer: Tracer) -> ActionOutcome:
        if blocked := self.check(req):
            return ActionOutcome("blocked", detail=blocked)
        tool = self.tools[req.tool]
        if tool.risk is not Risk.READ and not await approver(req):
            return ActionOutcome("denied", detail="human did not approve")
        if self.dry_run:
            return ActionOutcome("dry_run", detail=f"would run {req.tool}({req.args})")
        text, is_error = run_tool(tool, req.args, tracer, agent="remediator")
        result = json.loads(text)
        if is_error:
            return ActionOutcome("failed", result, detail=result.get("error", ""))
        return ActionOutcome("executed", result)
