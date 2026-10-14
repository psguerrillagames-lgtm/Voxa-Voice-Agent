"""Multi-agent incident investigation.

    alert
      -> planner        (RAG runbooks + recalled past incidents -> hypotheses, tasks)
      -> specialists    (logs / metrics / deploys, ReAct loops in parallel, read-only)
      -> synthesizer    (structured Diagnosis with one proposed action)
      -> critic         (reflection: reject + revise, up to N rounds)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from voxa.agents import prompts
from voxa.agents.react import AgentResult, run_react
from voxa.llm import LLMClient
from voxa.memory import IncidentMemory
from voxa.observability import Tracer
from voxa.rag import KnowledgeBase
from voxa.schemas import Critique, Diagnosis, Plan
from voxa.sim.infra import Infra
from voxa.tools import read_tools
from voxa.tools.base import Tool

SPECIALIST_TOOLS = {
    "logs": {"search_logs", "service_status", "search_runbooks"},
    "metrics": {"get_metrics", "service_status"},
    "deploys": {"recent_deploys", "get_config", "search_runbooks"},
}


@dataclass
class Investigation:
    alert: dict
    plan: Plan
    findings: list[AgentResult]
    diagnosis: Diagnosis
    critiques: list[Critique] = field(default_factory=list)

    def findings_text(self) -> str:
        return "\n\n".join(f"## {f.agent} specialist\n{f.text}" for f in self.findings)


class Orchestrator:
    def __init__(self, llm: LLMClient, infra: Infra, kb: KnowledgeBase,
                 memory: IncidentMemory, tracer: Tracer, max_revisions: int = 1):
        self.llm, self.infra, self.kb, self.memory = llm, infra, kb, memory
        self.tracer = tracer
        self.max_revisions = max_revisions
        self.tools: dict[str, Tool] = {t.name: t for t in read_tools(infra)}
        self.tools["search_runbooks"] = kb.tool()

    def _tools_for(self, agent: str) -> list[Tool]:
        return [self.tools[name] for name in sorted(SPECIALIST_TOOLS[agent])]

    async def plan(self, alert: dict) -> Plan:
        query = f"{alert.get('service')} {alert.get('metric')} {alert.get('summary')}"
        context = (f"ALERT:\n{json.dumps(alert)}\n\n"
                   f"RELEVANT RUNBOOKS:\n{self.kb.context(query) or 'none'}\n\n"
                   f"SIMILAR PAST INCIDENTS:\n{self.memory.context(query) or 'none'}")
        plan = await self.llm.parse(agent="planner", system=prompts.PLANNER,
                                    messages=[{"role": "user", "content": context}],
                                    output_format=Plan)
        self.tracer.emit({"type": "plan", "plan": plan.model_dump()})
        return plan

    async def run_specialists(self, alert: dict, plan: Plan) -> list[AgentResult]:
        # One task per specialist; if the planner assigned two, merge them.
        merged: dict[str, list[str]] = {}
        for task in plan.tasks:
            merged.setdefault(task.agent, []).append(task.instruction)
        jobs = [
            run_react(self.llm, agent=agent, system=prompts.SPECIALIST[agent],
                      task=(f"Alert: {json.dumps(alert)}\nHypotheses: {plan.hypotheses}\n"
                            f"Your task: {' '.join(instructions)}"),
                      tools=self._tools_for(agent), tracer=self.tracer)
            for agent, instructions in merged.items()
        ]
        return list(await asyncio.gather(*jobs))

    async def synthesize(self, alert: dict, plan: Plan, findings: list[AgentResult],
                         feedback: list[str] | None = None) -> Diagnosis:
        body = (f"ALERT:\n{json.dumps(alert)}\n\nHYPOTHESES:\n{plan.hypotheses}\n\n"
                f"FINDINGS:\n" + "\n\n".join(f"## {f.agent}\n{f.text}" for f in findings)
                + f"\n\nRUNBOOKS:\n{self.kb.context(' '.join(f.text for f in findings)[:2000])}")
        if feedback:
            body += ("\n\nA reviewer rejected your previous diagnosis. Fix these issues:\n- "
                     + "\n- ".join(feedback))
        return await self.llm.parse(agent="synthesizer", system=prompts.SYNTHESIZER,
                                    messages=[{"role": "user", "content": body}],
                                    output_format=Diagnosis)

    async def critique(self, findings: list[AgentResult], diagnosis: Diagnosis) -> Critique:
        body = ("FINDINGS:\n" + "\n\n".join(f"## {f.agent}\n{f.text}" for f in findings)
                + f"\n\nPROPOSED DIAGNOSIS:\n{diagnosis.model_dump_json(indent=2)}")
        return await self.llm.parse(agent="critic", system=prompts.CRITIC,
                                    messages=[{"role": "user", "content": body}],
                                    output_format=Critique)

    async def investigate(self, alert: dict) -> Investigation:
        with self.tracer.span("agent", "investigation", agent="orchestrator"):
            plan = await self.plan(alert)
            findings = await self.run_specialists(alert, plan)
            diagnosis = await self.synthesize(alert, plan, findings)
            critiques = []
            for _ in range(self.max_revisions + 1):
                review = await self.critique(findings, diagnosis)
                critiques.append(review)
                self.tracer.emit({"type": "critique", **review.model_dump()})
                if review.approved or len(critiques) > self.max_revisions:
                    break
                diagnosis = await self.synthesize(alert, plan, findings, review.issues)
            self.tracer.emit({"type": "diagnosis", "diagnosis": diagnosis.model_dump()})
            return Investigation(alert, plan, findings, diagnosis, critiques)
