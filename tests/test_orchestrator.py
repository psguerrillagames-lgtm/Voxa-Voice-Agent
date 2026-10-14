from fakes import FakeLLM, reply, text, tool_use

from voxa.agents.orchestrator import Orchestrator
from voxa.memory import IncidentMemory
from voxa.observability import Tracer
from voxa.rag import KnowledgeBase
from voxa.schemas import Critique, Diagnosis, Plan, ProposedAction, Task
from voxa.sim import SCENARIOS


def _diag(service, category, tool):
    return Diagnosis(root_cause_service=service, category=category, summary="s",
                     evidence=["e"], confidence=0.8,
                     action=ProposedAction(tool=tool, service=service, reason="r"),
                     spoken_briefing="Hi, checkout broke. Roll back?")


async def test_full_pipeline_with_critic_revision():
    scenario = SCENARIOS["bad_deploy_checkout"]
    infra = scenario.build()
    plan = Plan(hypotheses=["bad checkout deploy", "gateway issue"],
                tasks=[Task(agent="logs", instruction="errors in checkout"),
                       Task(agent="deploys", instruction="recent deploys")])
    llm = FakeLLM(
        scripts={
            "logs": [reply(tool_use("search_logs", service="checkout", level="ERROR")),
                     reply(text("checkout: connection pool exhausted since 10m ago"))],
            "deploys": [reply(tool_use("recent_deploys")),
                        reply(text("checkout v2.3.0 deployed 12m ago by alex"))],
        },
        parsed={
            "planner": [plan],
            # first answer blames the gateway (the symptom); critic rejects it
            "synthesizer": [_diag("api-gateway", "bad_deploy", "restart_service"),
                            _diag("checkout", "bad_deploy", "rollback_deploy")],
            "critic": [Critique(approved=False, issues=["gateway is a symptom"]),
                       Critique(approved=True, issues=[])],
        },
    )
    tracer = Tracer()
    orch = Orchestrator(llm, infra, KnowledgeBase.from_dir(), IncidentMemory(), tracer)

    result = await orch.investigate(scenario.alert)

    assert result.diagnosis.root_cause_service == "checkout"
    assert result.diagnosis.action.tool == "rollback_deploy"
    assert [c.approved for c in result.critiques] == [False, True]
    # planner saw RAG context; revised synthesis saw critic feedback
    planner_prompt = next(c for c in llm.calls if c["agent"] == "planner")["messages"][0]
    assert "connection-pool" in planner_prompt["content"] or "Runbook" in planner_prompt["content"]
    last_synth = [c for c in llm.calls if c["agent"] == "synthesizer"][-1]
    assert "gateway is a symptom" in last_synth["messages"][0]["content"]
    # specialists only got their own read-only tools
    logs_tools = {t["name"] for t in next(c for c in llm.calls if c["agent"] == "logs")["tools"]}
    assert logs_tools == {"search_logs", "service_status", "search_runbooks"}
    assert {s.agent for s in tracer.spans if s.kind == "tool"} == {"logs", "deploys"}
