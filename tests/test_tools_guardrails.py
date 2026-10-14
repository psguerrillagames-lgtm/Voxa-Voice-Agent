import json

from voxa.guardrails import ActionRequest, Policy
from voxa.observability import Tracer
from voxa.sim import SCENARIOS
from voxa.tools import Risk, action_tools, read_tools, run_tool


def _by_name(tools):
    return {t.name: t for t in tools}


def test_read_tools_return_json_and_errors_are_soft():
    infra = SCENARIOS["bad_deploy_checkout"].build()
    tools = _by_name(read_tools(infra))
    tracer = Tracer()
    text, err = run_tool(tools["search_logs"], {"service": "checkout", "level": "ERROR"}, tracer)
    assert not err and "pool exhausted" in text
    text, err = run_tool(tools["get_metrics"], {"service": "nope", "metric": "cpu_pct"}, tracer)
    assert err and "unknown service" in json.loads(text)["error"]
    _, err = run_tool(tools["get_config"], {"svc": "checkout"}, tracer)
    assert err


def test_all_read_tools_are_read_risk():
    infra = SCENARIOS["bad_deploy_checkout"].build()
    assert {t.risk for t in read_tools(infra)} == {Risk.READ}
    assert Risk.READ not in {t.risk for t in action_tools(infra)}


async def _yes(_req):
    return True


async def _no(_req):
    return False


async def test_policy_requires_approval_and_honours_dry_run():
    infra = SCENARIOS["bad_deploy_checkout"].build()
    tools = _by_name(action_tools(infra))
    req = ActionRequest("rollback_deploy", {"service": "checkout"}, Risk.DESTRUCTIVE, "bad deploy")

    denied = await Policy(tools, dry_run=False).execute(req, _no, Tracer())
    assert denied.status == "denied" and infra.services["checkout"].status == "degraded"

    dry = await Policy(tools, dry_run=True).execute(req, _yes, Tracer())
    assert dry.status == "dry_run" and infra.services["checkout"].status == "degraded"

    policy = Policy(tools, dry_run=False)
    done = await policy.execute(req, _yes, Tracer())
    assert done.status == "executed" and infra.services["checkout"].status == "healthy"
    assert policy.audit[-1]["status"] == "executed"


async def test_policy_blocks_unknown_tools_and_services():
    infra = SCENARIOS["bad_deploy_checkout"].build()
    policy = Policy(_by_name(action_tools(infra)), dry_run=False)
    out = await policy.execute(ActionRequest("drop_database", {"service": "checkout"},
                                             Risk.DESTRUCTIVE, ""), _yes, Tracer())
    assert out.status == "blocked"
    out = await policy.execute(ActionRequest("restart_service", {"service": "billing-db"},
                                             Risk.WRITE, ""), _yes, Tracer())
    assert out.status == "blocked"
