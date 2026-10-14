from fakes import FakeLLM, reply, text
from fastapi.testclient import TestClient

from voxa.memory import IncidentMemory
from voxa.schemas import Critique, Diagnosis, Plan, ProposedAction, ReplyIntent, Task
from voxa.server import create_app


def _llm(_tracer):
    diag = Diagnosis(root_cause_service="checkout", category="bad_deploy", summary="pool",
                     evidence=["e"], confidence=0.9,
                     action=ProposedAction(tool="rollback_deploy", service="checkout",
                                           reason="r"),
                     spoken_briefing="Hi, Voxa here. Checkout broke. Roll back?")
    return FakeLLM(
        scripts={"logs": [reply(text("pool exhausted"))]},
        parsed={"planner": [Plan(hypotheses=["h"], tasks=[Task(agent="logs", instruction="x")])],
                "synthesizer": [diag], "critic": [Critique(approved=True, issues=[])],
                "conversation": [ReplyIntent(intent="approve", speech="Rolling back.")]})


def test_trigger_scenario_then_approve_by_text():
    client = TestClient(create_app(llm_factory=_llm, memory=IncidentMemory(), voice_key=""))
    assert len(client.get("/scenarios").json()) == 5

    opened = client.post("/scenarios/bad_deploy_checkout/trigger").json()
    assert opened["transcript"][0] == {"speaker": "voxa",
                                       "text": "Hi, Voxa here. Checkout broke. Roll back?"}
    assert opened["state"] == "awaiting_approval" and opened["voice"] is False

    done = client.post(f"/incidents/{opened['id']}/reply", data={"text": "yes"}).json()
    assert done["heard"] == "yes" and done["audit"]

    assert client.get(f"/incidents/{opened['id']}/speech").status_code == 503
    assert client.get("/incidents/999").status_code == 404
    assert client.post(f"/incidents/{opened['id']}/reply", data={}).status_code == 400
