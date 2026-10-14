"""Fault-injection scenarios with ground truth, used by the demo and the eval suite.

Each scenario puts the Infra into a broken state and records the answer a good SRE
would reach: which service is the root cause, what kind of fault it is, and which
remediation fixes it. Most scenarios include a red herring (a symptom in a
downstream service, or an unrelated recent deploy).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from voxa.sim.infra import Anomaly, Infra

CATEGORIES = ("bad_deploy", "memory_leak", "config_error", "traffic_spike", "dependency_outage")
ACTIONS = ("rollback", "restart", "set_config", "scale", "escalate")


@dataclass(frozen=True)
class Scenario:
    name: str
    alert: dict
    root_service: str
    category: str
    action: str
    apply: Callable[[Infra, str], None]
    description: str = ""

    def build(self, seed: int = 7) -> Infra:
        infra = Infra(seed=seed)
        self.apply(infra, self.root_service)
        infra.fault_kind = (self.category, self.root_service)
        return infra


def _bad_deploy(infra: Infra, svc: str) -> None:
    infra.add_deploy(svc, "v2.3.0", infra.services[svc].version, "alex", 12,
                     "Refactor DB client, new connection pooling")
    infra.anomalies += [Anomaly(svc, "latency_p99_ms", 11, 4.2),
                        Anomaly(svc, "error_rate_pct", 11, 35),
                        Anomaly("api-gateway", "latency_p99_ms", 11, 1.8)]
    infra.services[svc].status = "degraded"
    for m in (10, 8, 6, 4, 2, 1):
        infra.log(svc, "ERROR", "TimeoutError: connection pool exhausted (size=5, waited 3000ms)", m)
    infra.log("api-gateway", "WARN", f"upstream {svc} slow response 2.9s", 3)


def _memory_leak(infra: Infra, svc: str) -> None:
    infra.anomalies += [Anomaly(svc, "memory_pct", 55, 2.1, ramp=True),
                        Anomaly(svc, "latency_p99_ms", 15, 2.5)]
    infra.services[svc].status = "degraded"
    for m in (40, 25, 12):
        infra.log(svc, "WARN", "GC pause 1.8s, heap usage 91%", m)
    infra.log(svc, "ERROR", "container OOMKilled, restarting (restart_count=3)", 5)
    infra.log(svc, "ERROR", "java.lang.OutOfMemoryError: Java heap space", 4)


def _config_error(infra: Infra, svc: str) -> None:
    infra.services[svc].config["CACHE_HOST"] = "redis-prod.internl:6379"
    infra.anomalies += [Anomaly(svc, "error_rate_pct", 20, 60)]
    infra.services[svc].status = "crashloop"
    for m in (19, 14, 9, 4, 1):
        infra.log(svc, "ERROR", "Failed to resolve host redis-prod.internl: Name or service "
                  "not known (config CACHE_HOST)", m)
    infra.log(svc, "INFO", "config reloaded from config-service (change by ops-bot)", 20)


def _traffic_spike(infra: Infra, svc: str) -> None:
    infra.anomalies += [Anomaly(svc, "rps", 18, 3.5), Anomaly(svc, "cpu_pct", 18, 2.6),
                        Anomaly(svc, "latency_p99_ms", 16, 2.2)]
    infra.services[svc].status = "degraded"
    for m in (15, 9, 3):
        infra.log(svc, "WARN", "request queue depth 1200, CPU throttled", m)
    infra.log("api-gateway", "INFO", "marketing campaign 'flash-sale' traffic routed", 19)


def _dependency_outage(infra: Infra, svc: str) -> None:
    infra.anomalies += [Anomaly(svc, "error_rate_pct", 9, 40),
                        Anomaly("checkout", "error_rate_pct", 8, 12)]
    infra.services[svc].status = "degraded"
    for m in (8, 6, 3, 1):
        infra.log(svc, "ERROR", "upstream bank-gateway.partner.com returned 503 Service "
                  "Unavailable", m)
    infra.log("checkout", "ERROR", f"{svc} call failed: 502 bad gateway", 2)


def _alert(service: str, metric: str, text: str) -> dict:
    return {"source": "prometheus", "severity": "critical", "service": service,
            "metric": metric, "summary": text}


SCENARIOS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("bad_deploy_checkout",
             _alert("api-gateway", "latency_p99_ms", "p99 latency above 200ms for 10 minutes"),
             "checkout", "bad_deploy", "rollback", _bad_deploy,
             "Deploy v2.3.0 shrank the DB pool; gateway latency is only a symptom."),
    Scenario("memory_leak_payments",
             _alert("payments", "latency_p99_ms", "payments p99 latency above 300ms"),
             "payments", "memory_leak", "restart", _memory_leak,
             "Heap climbs for an hour until OOMKills; no recent deploy."),
    Scenario("config_error_recommendations",
             _alert("recommendations", "error_rate_pct", "error rate above 5%"),
             "recommendations", "config_error", "set_config", _config_error,
             "Typo in CACHE_HOST pushed by config-service."),
    Scenario("traffic_spike_checkout",
             _alert("checkout", "latency_p99_ms", "checkout p99 latency above 250ms"),
             "checkout", "traffic_spike", "scale", _traffic_spike,
             "Flash-sale traffic, healthy code; needs more replicas."),
    Scenario("dependency_outage_payments",
             _alert("checkout", "error_rate_pct", "checkout error rate above 5%"),
             "payments", "dependency_outage", "escalate", _dependency_outage,
             "Third-party bank gateway is down; nothing to roll back, page the vendor."),
]}
