from voxa.sim import SCENARIOS, Infra


def test_baseline_is_healthy():
    infra = Infra()
    assert all(s["status"] == "healthy" for s in infra.status())
    assert infra.search_logs(level="ERROR") == []


def test_bad_deploy_shows_up_in_metrics_logs_and_deploys():
    infra = SCENARIOS["bad_deploy_checkout"].build()
    series = infra.metric_series("checkout", "latency_p99_ms")
    assert series[-1]["value"] > 3 * series[0]["value"]
    assert any("pool exhausted" in log["message"] for log in infra.search_logs("checkout"))
    assert infra.recent_deploys()[0]["service"] == "checkout"


def test_correct_remediation_clears_fault():
    infra = SCENARIOS["bad_deploy_checkout"].build()
    infra.restart("checkout")  # wrong fix
    assert infra.services["checkout"].status == "degraded"
    infra.rollback("checkout")
    assert infra.services["checkout"].status == "healthy"
    assert infra.services["checkout"].version == "v2.2.0"


def test_memory_leak_ramps():
    infra = SCENARIOS["memory_leak_payments"].build()
    mem = [p["value"] for p in infra.metric_series("payments", "memory_pct")]
    assert mem[-1] > mem[len(mem) // 2] > mem[0]


def test_every_scenario_builds():
    for scenario in SCENARIOS.values():
        infra = scenario.build()
        assert infra.services[scenario.root_service].status != "healthy"
