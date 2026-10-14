"""Expose Voxa's read-only SRE tools and runbook search over MCP.

Any MCP client (Claude Desktop, Claude Code, Copilot, other agents) can then
investigate the same environment Voxa's agents see. Write actions are not
exposed: they stay behind the approval-gated guardrail policy.

    python -m voxa.mcp_server                    # stdio
    python -m voxa.mcp_server --scenario bad_deploy_checkout
"""

from __future__ import annotations

import argparse
import json

from mcp.server.mcpserver import MCPServer

from voxa.rag import KnowledgeBase
from voxa.sim import SCENARIOS, Infra
from voxa.tools import read_tools


def build_server(infra: Infra, kb: KnowledgeBase | None = None) -> MCPServer:
    server = MCPServer("voxa-sre", instructions="Read-only SRE tools: status, metrics, "
                       "logs, deploys, config and runbook search for the Voxa environment.")
    tools = {t.name: t for t in read_tools(infra)}
    kb = kb or KnowledgeBase.from_dir()

    def call(name: str, **args) -> str:
        return json.dumps(tools[name].fn(**{k: v for k, v in args.items() if v is not None}))

    @server.tool(description=tools["service_status"].description)
    def service_status() -> str:
        return call("service_status")

    @server.tool(description=tools["get_metrics"].description)
    def get_metrics(service: str, metric: str, minutes: int = 60) -> str:
        return call("get_metrics", service=service, metric=metric, minutes=minutes)

    @server.tool(description=tools["search_logs"].description)
    def search_logs(service: str | None = None, query: str = "", level: str | None = None,
                    minutes: int = 60) -> str:
        return call("search_logs", service=service, query=query, level=level, minutes=minutes)

    @server.tool(description=tools["recent_deploys"].description)
    def recent_deploys(hours: int = 24) -> str:
        return call("recent_deploys", hours=hours)

    @server.tool(description=tools["get_config"].description)
    def get_config(service: str) -> str:
        return call("get_config", service=service)

    @server.tool(description="Search internal runbooks and past postmortems.")
    def search_runbooks(query: str) -> str:
        return json.dumps(kb.search(query, 3))

    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default=None)
    args = parser.parse_args()
    infra = SCENARIOS[args.scenario].build() if args.scenario else Infra()
    build_server(infra).run("stdio")


if __name__ == "__main__":
    main()
