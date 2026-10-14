"""A live incident call: Voxa speaks first, then converses until resolved.

    alert -> investigate -> Voxa opens the call with its briefing (AI-initiated)
          -> engineer replies -> intent (approve / deny / question / alternative)
          -> approved action runs through the guardrail policy
          -> Voxa verifies recovery, reports back, and saves the incident to memory
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from voxa.agents import prompts
from voxa.agents.orchestrator import Investigation, Orchestrator
from voxa.guardrails import ActionOutcome, ActionRequest, Policy
from voxa.llm import LLMClient
from voxa.memory import IncidentMemory, IncidentRecord
from voxa.observability import Tracer
from voxa.schemas import ProposedAction, ReplyIntent
from voxa.sim.infra import Infra
from voxa.tools.base import Risk


@dataclass
class Turn:
    speaker: str  # voxa | engineer
    text: str


@dataclass
class IncidentSession:
    llm: LLMClient
    infra: Infra
    orchestrator: Orchestrator
    policy: Policy
    memory: IncidentMemory
    tracer: Tracer
    state: str = "new"  # new | investigating | awaiting_approval | resolved | escalated | standby
    investigation: Investigation | None = None
    proposed: ProposedAction | None = None
    transcript: list[Turn] = field(default_factory=list)
    outcome: ActionOutcome | None = None

    def _say(self, text: str) -> str:
        self.transcript.append(Turn("voxa", text))
        self.tracer.emit({"type": "voxa_says", "text": text, "state": self.state})
        return text

    async def start(self, alert: dict) -> str:
        """Run the investigation and return Voxa's opening line for the call."""
        self.state = "investigating"
        self.tracer.emit({"type": "alert", "alert": alert})
        self.investigation = await self.orchestrator.investigate(alert)
        diagnosis = self.investigation.diagnosis
        self.proposed = diagnosis.action
        if diagnosis.action.tool == "escalate":
            self.state = "escalated"
        else:
            self.state = "awaiting_approval"
        return self._say(diagnosis.spoken_briefing)

    async def reply(self, utterance: str) -> str:
        if self.investigation is None:
            raise RuntimeError("call start() first")
        self.transcript.append(Turn("engineer", utterance))
        intent = await self._classify(utterance)
        self.tracer.emit({"type": "intent", **intent.model_dump()})

        if intent.intent == "alternative" and intent.alternative:
            self.proposed = intent.alternative
            self.state = "awaiting_approval"
            return self._say(intent.speech)
        if intent.intent == "deny":
            self.state = "standby"
            return self._say(intent.speech)
        if intent.intent == "approve" and self.state == "awaiting_approval" and self.proposed:
            return self._say(f"{intent.speech} {await self._run_approved()}".strip())
        return self._say(intent.speech)

    async def _classify(self, utterance: str) -> ReplyIntent:
        inv = self.investigation
        context = {
            "state": self.state,
            "diagnosis": inv.diagnosis.model_dump(),
            "currently_proposed_action": self.proposed.model_dump() if self.proposed else None,
            "findings": inv.findings_text()[:4000],
            "transcript": [f"{t.speaker}: {t.text}" for t in self.transcript[-8:]],
        }
        return await self.llm.parse(
            agent="conversation", system=prompts.CONVERSATION,
            messages=[{"role": "user", "content": f"CONTEXT:\n{json.dumps(context)}\n\n"
                                                  f"ENGINEER SAID: {utterance}"}],
            output_format=ReplyIntent)

    async def _run_approved(self) -> str:
        action = self.proposed
        if action.tool == "escalate":
            self.state = "escalated"
            return "I've paged the owning team and the vendor."
        tool = self.policy.tools.get(action.tool)
        # Unknown tools are blocked by the policy; treat them as worst-case risk.
        risk = tool.risk if tool else Risk.DESTRUCTIVE
        req = ActionRequest(action.tool, action.args(), risk, action.reason)

        async def approved_by_voice(r: ActionRequest) -> bool:
            # The engineer approved exactly this action on the call.
            return r.tool == action.tool and r.args == action.args()

        with self.tracer.span("action", action.tool, agent="remediator", args=req.args):
            self.outcome = await self.policy.execute(req, approved_by_voice, self.tracer)

        service = action.service
        if self.outcome.status == "dry_run":
            self.state = "resolved"
            return f"Dry run mode is on, so I only simulated {action.tool} on {service}."
        if self.outcome.status != "executed":
            self.state = "standby"
            return f"That action was {self.outcome.status}: {self.outcome.detail}."
        healthy = self.infra.services[service].status == "healthy"
        self.state = "resolved" if healthy else "awaiting_approval"
        self._remember(healthy)
        if healthy:
            return f"Done. {service} is healthy again and metrics are back to baseline."
        return f"I ran it, but {service} is still {self.infra.services[service].status}."

    def _remember(self, worked: bool) -> None:
        d = self.investigation.diagnosis
        self.memory.remember(IncidentRecord(
            alert=self.investigation.alert, root_service=d.root_cause_service,
            category=d.category, summary=d.summary, action=self.proposed.tool,
            outcome="resolved" if worked else "did_not_help",
            lesson=(f"{d.category} on {d.root_cause_service}: {self.proposed.tool} "
                    f"{'fixed it' if worked else 'did not fix it'}")))
