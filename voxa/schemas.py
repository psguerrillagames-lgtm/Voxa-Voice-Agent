"""Structured outputs exchanged between agents (validated via Pydantic)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Specialist = Literal["logs", "metrics", "deploys"]
Category = Literal["bad_deploy", "memory_leak", "config_error", "traffic_spike",
                   "dependency_outage", "unknown"]
ActionTool = Literal["rollback_deploy", "restart_service", "scale_service", "set_config",
                     "escalate"]


class Task(BaseModel):
    agent: Specialist
    instruction: str = Field(description="What this specialist should check, concretely")


class Plan(BaseModel):
    hypotheses: list[str] = Field(description="2-4 candidate root causes, most likely first")
    tasks: list[Task] = Field(description="One task per specialist worth running")


class ProposedAction(BaseModel):
    tool: ActionTool
    service: str
    replicas: int | None = None
    key: str | None = None
    value: str | None = None
    reason: str

    def args(self) -> dict:
        out: dict = {"service": self.service}
        if self.tool == "scale_service":
            out["replicas"] = self.replicas
        if self.tool == "set_config":
            out |= {"key": self.key, "value": self.value}
        return out


class Diagnosis(BaseModel):
    root_cause_service: str
    category: Category
    summary: str = Field(description="One or two sentences for an engineer")
    evidence: list[str] = Field(description="Specific observations with numbers/timestamps")
    confidence: float = Field(description="0.0 to 1.0")
    action: ProposedAction
    spoken_briefing: str = Field(
        description="What Voxa says when the on-call picks up: under 60 words, plain speech, "
                    "no markdown, ends by asking for approval of the action")


class Critique(BaseModel):
    approved: bool
    issues: list[str] = Field(description="Concrete problems; empty if approved")


class ReplyIntent(BaseModel):
    intent: Literal["approve", "deny", "question", "alternative", "other"]
    alternative: ProposedAction | None = Field(
        default=None, description="Only when the engineer asks for a different action")
    speech: str = Field(description="Voxa's spoken reply, under 50 words, no markdown")
