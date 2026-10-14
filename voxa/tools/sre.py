"""SRE tools over the (simulated) production environment.

Read tools go to the investigating agents. Action tools are only ever executed
through the guardrail policy after a human approves.
"""

from __future__ import annotations

from voxa.sim.infra import METRICS, Infra
from voxa.tools.base import Risk, Tool, ToolError, schema

SERVICE = {"type": "string", "description": "Service name, e.g. 'checkout'"}


def _service(infra: Infra, name: str) -> str:
    if name not in infra.services:
        raise ToolError(f"unknown service '{name}'. Known: {sorted(infra.services)}")
    return name


def read_tools(infra: Infra) -> list[Tool]:
    def service_status() -> list[dict]:
        return infra.status()

    def get_metrics(service: str, metric: str, minutes: int = 60) -> dict:
        if metric not in METRICS:
            raise ToolError(f"unknown metric '{metric}'. Known: {list(METRICS)}")
        series = infra.metric_series(_service(infra, service), metric, min(minutes, 180))
        values = [p["value"] for p in series]
        return {"service": service, "metric": metric, "points": series,
                "min": min(values), "max": max(values), "latest": values[-1]}

    def search_logs(service: str | None = None, query: str = "", level: str | None = None,
                    minutes: int = 60) -> list[dict]:
        if service is not None:
            _service(infra, service)
        return infra.search_logs(service, query, level, min(minutes, 180))

    def recent_deploys(hours: int = 24) -> list[dict]:
        return infra.recent_deploys(min(hours, 72))

    def get_config(service: str) -> dict:
        return infra.config(_service(infra, service))

    return [
        Tool("service_status", "Current status, version, replicas and latest metrics for "
             "every service. Start here to see what is unhealthy.",
             schema({}), service_status),
        Tool("get_metrics", f"Time series for one metric of one service. Metrics: "
             f"{', '.join(METRICS)}. Use to find when a change started.",
             schema({"service": SERVICE, "metric": {"type": "string", "enum": list(METRICS)}},
                    {"minutes": {"type": "integer", "description": "Lookback, max 180"}}),
             get_metrics),
        Tool("search_logs", "Search recent log lines. Filter by service, substring query and "
             "level (INFO, WARN, ERROR). Newest first.",
             schema({}, {"service": SERVICE, "query": {"type": "string"},
                         "level": {"type": "string", "enum": ["INFO", "WARN", "ERROR"]},
                         "minutes": {"type": "integer"}}),
             search_logs),
        Tool("recent_deploys", "Deploys across all services, newest first, with version, "
             "author and how many minutes ago.",
             schema({}, {"hours": {"type": "integer"}}), recent_deploys),
        Tool("get_config", "Current runtime config key/values for a service.",
             schema({"service": SERVICE}), get_config),
    ]


def action_tools(infra: Infra) -> list[Tool]:
    def rollback_deploy(service: str) -> dict:
        return infra.rollback(_service(infra, service))

    def restart_service(service: str) -> dict:
        return infra.restart(_service(infra, service))

    def scale_service(service: str, replicas: int) -> dict:
        if not 1 <= replicas <= 20:
            raise ToolError("replicas must be between 1 and 20")
        return infra.scale(_service(infra, service), replicas)

    def set_config(service: str, key: str, value: str) -> dict:
        return infra.set_config(_service(infra, service), key, value)

    return [
        Tool("rollback_deploy", "Roll a service back to the version before its latest deploy.",
             schema({"service": SERVICE}), rollback_deploy, Risk.DESTRUCTIVE),
        Tool("restart_service", "Rolling restart of all replicas of a service.",
             schema({"service": SERVICE}), restart_service, Risk.WRITE),
        Tool("scale_service", "Set the replica count of a service (1-20).",
             schema({"service": SERVICE, "replicas": {"type": "integer"}}),
             scale_service, Risk.WRITE),
        Tool("set_config", "Change one runtime config value of a service.",
             schema({"service": SERVICE, "key": {"type": "string"},
                     "value": {"type": "string"}}),
             set_config, Risk.WRITE),
    ]
