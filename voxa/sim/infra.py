"""Simulated production environment: services, deploys, logs and metrics.

The agents never see this module directly; they only reach it through tools,
exactly as they would reach a real observability stack.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

NOW = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)

METRICS = ("latency_p99_ms", "error_rate_pct", "cpu_pct", "memory_pct", "rps")


@dataclass
class Service:
    name: str
    version: str
    replicas: int = 3
    status: str = "healthy"
    config: dict[str, str] = field(default_factory=dict)
    baseline: dict[str, float] = field(default_factory=dict)


@dataclass
class Deploy:
    id: str
    service: str
    version: str
    previous_version: str
    author: str
    at: datetime
    summary: str


@dataclass
class LogLine:
    at: datetime
    service: str
    level: str
    message: str


@dataclass
class Anomaly:
    """A metric shift that starts `start_min` minutes ago."""

    service: str
    metric: str
    start_min: int
    factor: float = 1.0
    ramp: bool = False  # gradual climb (leaks) instead of a step change


class Infra:
    def __init__(self, seed: int = 7):
        self.seed = seed
        self.services: dict[str, Service] = {}
        self.deploys: list[Deploy] = []
        self.logs: list[LogLine] = []
        self.anomalies: list[Anomaly] = []
        self.actions: list[dict] = []
        # (kind, service) of the injected fault; remediation clears it when it matches
        self.fault_kind: tuple[str, str] | None = None
        self._build_baseline()

    # ---------------------------------------------------------------- setup
    def _build_baseline(self) -> None:
        base = {"latency_p99_ms": 120, "error_rate_pct": 0.2, "cpu_pct": 35,
                "memory_pct": 45, "rps": 400}
        for name, version in [("api-gateway", "v5.1.0"), ("checkout", "v2.2.0"),
                              ("payments", "v3.4.1"), ("inventory", "v1.9.0"),
                              ("recommendations", "v4.0.2")]:
            self.services[name] = Service(
                name, version, baseline=dict(base),
                config={"DB_POOL_SIZE": "50", "LOG_LEVEL": "info"},
            )
        self.add_deploy("inventory", "v1.9.0", "v1.8.3", "maria", 26 * 60, "Add SKU cache")
        self.add_deploy("api-gateway", "v5.1.0", "v5.0.9", "dev-bot", 9 * 60, "Bump deps")
        for i in range(0, 60, 4):
            for svc in self.services:
                self.log(svc, "INFO", "request served ok", minutes_ago=i)

    def add_deploy(self, service: str, version: str, previous: str, author: str,
                   minutes_ago: int, summary: str) -> Deploy:
        d = Deploy(f"dep-{len(self.deploys) + 101}", service, version, previous, author,
                   NOW - timedelta(minutes=minutes_ago), summary)
        self.deploys.append(d)
        self.services[service].version = version
        return d

    def log(self, service: str, level: str, message: str, minutes_ago: float = 0) -> None:
        self.logs.append(LogLine(NOW - timedelta(minutes=minutes_ago), service, level, message))

    # --------------------------------------------------------------- queries
    def metric_series(self, service: str, metric: str, minutes: int = 60,
                      step: int = 5) -> list[dict]:
        svc = self.services[service]
        rng = random.Random(f"{self.seed}-{service}-{metric}")
        points = []
        for m in range(minutes, -1, -step):
            value = svc.baseline[metric] * (1 + rng.uniform(-0.05, 0.05))
            for a in self.anomalies:
                if a.service == service and a.metric == metric and m <= a.start_min:
                    if a.ramp:
                        progress = (a.start_min - m) / max(a.start_min, 1)
                        value *= 1 + (a.factor - 1) * progress
                    else:
                        value *= a.factor
            points.append({"minutes_ago": m, "value": round(value, 2)})
        return points

    def search_logs(self, service: str | None = None, query: str = "",
                    level: str | None = None, minutes: int = 60, limit: int = 20) -> list[dict]:
        cutoff = NOW - timedelta(minutes=minutes)
        q = query.lower()
        hits = [
            line for line in self.logs
            if line.at >= cutoff
            and (service is None or line.service == service)
            and (level is None or line.level == level.upper())
            and (not q or q in line.message.lower())
        ]
        hits.sort(key=lambda line: line.at, reverse=True)
        return [{"minutes_ago": round((NOW - h.at).total_seconds() / 60, 1),
                 "service": h.service, "level": h.level, "message": h.message}
                for h in hits[:limit]]

    def recent_deploys(self, hours: int = 24) -> list[dict]:
        cutoff = NOW - timedelta(hours=hours)
        return [{"id": d.id, "service": d.service, "version": d.version,
                 "previous_version": d.previous_version, "author": d.author,
                 "minutes_ago": int((NOW - d.at).total_seconds() // 60), "summary": d.summary}
                for d in sorted(self.deploys, key=lambda d: d.at, reverse=True) if d.at >= cutoff]

    def status(self) -> list[dict]:
        out = []
        for s in self.services.values():
            latest = {m: self.metric_series(s.name, m, minutes=0)[-1]["value"] for m in METRICS}
            out.append({"service": s.name, "version": s.version, "replicas": s.replicas,
                        "status": s.status, "metrics": latest})
        return out

    # --------------------------------------------------------------- actions
    def clear_service(self, service: str) -> None:
        self.anomalies = [a for a in self.anomalies if a.service != service]
        self.services[service].status = "healthy"

    def rollback(self, service: str) -> dict:
        deploy = next((d for d in sorted(self.deploys, key=lambda d: d.at, reverse=True)
                       if d.service == service), None)
        if deploy is None:
            return {"ok": False, "error": f"no deploy found for {service}"}
        self.add_deploy(service, deploy.previous_version, deploy.version, "voxa", 0,
                        f"Rollback of {deploy.id}")
        if self.fault_kind == ("bad_deploy", service):
            self.clear_service(service)
        return {"ok": True, "service": service, "version": deploy.previous_version}

    def restart(self, service: str) -> dict:
        if self.fault_kind == ("memory_leak", service):
            self.clear_service(service)
        return {"ok": True, "service": service, "note": "rolling restart complete"}

    def scale(self, service: str, replicas: int) -> dict:
        old = self.services[service].replicas
        self.services[service].replicas = replicas
        if self.fault_kind == ("traffic_spike", service) and replicas > old:
            self.clear_service(service)
        return {"ok": True, "service": service, "replicas": replicas, "previous": old}

    def set_config(self, service: str, key: str, value: str) -> dict:
        svc = self.services[service]
        old = svc.config.get(key)
        svc.config[key] = value
        if self.fault_kind == ("config_error", service):
            self.clear_service(service)
        return {"ok": True, "service": service, "key": key, "old": old, "new": value}

    def config(self, service: str) -> dict:
        return dict(self.services[service].config)
