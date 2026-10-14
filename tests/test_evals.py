from evals.run_evals import ACTION_OF_TOOL, cases, report
from voxa.sim.scenarios import ACTIONS


def test_twenty_distinct_cases_that_all_break_their_root_service():
    all_cases = cases()
    assert len(all_cases) == 20 and len({c.name for c in all_cases}) == 20
    for c in all_cases:
        assert c.build().services[c.root_service].status != "healthy", c.name


def test_action_mapping_covers_every_tool_and_report_renders():
    assert set(ACTION_OF_TOOL.values()) == set(ACTIONS)
    rows = [{"case": "a", "service_ok": True, "category_ok": True, "action_ok": True,
             "expected": "x", "predicted": "x", "seconds": 2.0, "cost_usd": 0.01},
            {"case": "b", "error": "boom"}]
    assert "| 2 | 50% | 50% | 50% | 50% |" in report(rows)
