from fakes import FakeLLM, reply, text, tool_use

from voxa.agents.react import run_react
from voxa.observability import Tracer
from voxa.sim import SCENARIOS
from voxa.tools import read_tools


async def test_react_loop_calls_tools_and_returns_answer():
    infra = SCENARIOS["bad_deploy_checkout"].build()
    llm = FakeLLM({"logs": [
        reply(text("Checking checkout errors."),
              tool_use("search_logs", service="checkout", level="ERROR"),
              tool_use("recent_deploys")),
        reply(text("Pool exhausted since deploy v2.3.0.")),
    ]})
    tracer = Tracer()
    thoughts = []
    tracer.subscribe(lambda e: e["type"] == "thought" and thoughts.append(e["text"]))

    result = await run_react(llm, agent="logs", system="s", task="investigate",
                             tools=read_tools(infra), tracer=tracer)

    assert result.text == "Pool exhausted since deploy v2.3.0."
    assert result.steps == 2 and [c["tool"] for c in result.tool_calls] == [
        "search_logs", "recent_deploys"]
    # Both tool results returned together in one user message.
    second_call = llm.calls[1]["messages"]
    assert [b["type"] for b in second_call[-1]["content"]] == ["tool_result", "tool_result"]
    assert "pool exhausted" in second_call[-1]["content"][0]["content"]
    assert thoughts == ["Checking checkout errors.", "Pool exhausted since deploy v2.3.0."]


async def test_unknown_tool_and_step_limit():
    infra = SCENARIOS["bad_deploy_checkout"].build()
    llm = FakeLLM({"a": [reply(tool_use("rm_rf")) for _ in range(3)]})
    result = await run_react(llm, agent="a", system="s", task="t", tools=read_tools(infra),
                             tracer=Tracer(), max_steps=3)
    assert result.stop_reason == "max_steps"
    assert all(c["error"] for c in result.tool_calls)


async def test_pause_turn_is_resumed():
    infra = SCENARIOS["bad_deploy_checkout"].build()
    llm = FakeLLM({"a": [reply(text("..."), stop="pause_turn"), reply(text("done"))]})
    result = await run_react(llm, agent="a", system="s", task="t", tools=read_tools(infra),
                             tracer=Tracer())
    assert result.text == "done" and result.steps == 2
