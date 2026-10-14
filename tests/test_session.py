from fakes import FakeLLM, reply, text

from voxa.agents.orchestrator import Orchestrator
from voxa.guardrails import Policy
from voxa.memory import IncidentMemory
from voxa.observability import Tracer
from voxa.rag import KnowledgeBase
from voxa.schemas import Critique, Diagnosis, Plan, ProposedAction, ReplyIntent, Task
from voxa.session import IncidentSession
from voxa.sim import SCENARIOS
from voxa.tools import action_tools

BRIEFING = "Hi, this is Voxa. Checkout broke after deploy v2.3. Shall I roll it back?"


def _session(intents, dry_run=False):
    scenario = SCENARIOS["bad_deploy_checkout"]
    infra = scenario.build()
    diag = Diagnosis(root_cause_service="checkout", category="bad_deploy", summary="pool",
                     evidence=["pool exhausted"], confidence=0.9,
                     action=ProposedAction(tool="rollback_deploy", service="checkout",
                                           reason="bad deploy"),
                     spoken_briefing=BRIEFING)
    llm = FakeLLM(
        scripts={"logs": [reply(text("pool exhausted"))]},
        parsed={"planner": [Plan(hypotheses=["deploy"],
                                 tasks=[Task(agent="logs", instruction="errors")])],
                "synthesizer": [diag], "critic": [Critique(approved=True, issues=[])],
                "conversation": intents})
    tracer, memory = Tracer(), IncidentMemory()
    orch = Orchestrator(llm, infra, KnowledgeBase.from_dir(), memory, tracer)
    policy = Policy({t.name: t for t in action_tools(infra)}, dry_run=dry_run)
    return IncidentSession(llm, infra, orch, policy, memory, tracer), scenario


async def test_voxa_speaks_first_then_runs_approved_action():
    session, scenario = _session([
        ReplyIntent(intent="question", speech="The pool dropped to five connections."),
        ReplyIntent(intent="approve", speech="Rolling back now."),
    ])
    opening = await session.start(scenario.alert)
    assert opening == BRIEFING
    assert session.transcript[0].speaker == "voxa"  # AI-initiated call
    assert session.state == "awaiting_approval"

    answer = await session.reply("why is it slow?")
    assert "five connections" in answer and session.infra.services["checkout"].status != "healthy"

    final = await session.reply("yes, do it")
    assert "healthy again" in final and session.state == "resolved"
    assert session.memory.recall("checkout bad_deploy")[0]["outcome"] == "resolved"
    assert session.policy.audit[-1]["status"] == "executed"


async def test_deny_takes_no_action():
    session, scenario = _session([ReplyIntent(intent="deny", speech="Okay, standing by.")])
    await session.start(scenario.alert)
    await session.reply("no, wait")
    assert session.state == "standby" and session.policy.audit == []


async def test_alternative_needs_fresh_approval_and_wrong_fix_is_reported():
    restart = ProposedAction(tool="restart_service", service="checkout", reason="try restart")
    session, scenario = _session([
        ReplyIntent(intent="alternative", alternative=restart, speech="Restart instead?"),
        ReplyIntent(intent="approve", speech="Restarting."),
    ])
    await session.start(scenario.alert)
    await session.reply("just restart it")
    assert session.proposed.tool == "restart_service" and session.policy.audit == []
    final = await session.reply("yes")
    assert "still degraded" in final
    assert session.memory.recall("checkout")[0]["outcome"] == "did_not_help"


async def test_dry_run_simulates_only():
    session, scenario = _session([ReplyIntent(intent="approve", speech="Okay.")], dry_run=True)
    await session.start(scenario.alert)
    assert "Dry run" in await session.reply("go")
    assert session.infra.services["checkout"].status == "degraded"
