from voxa.mcp_server import build_server
from voxa.sim import SCENARIOS


async def test_mcp_exposes_read_only_tools():
    server = build_server(SCENARIOS["bad_deploy_checkout"].build())
    names = {t.name for t in await server.list_tools()}
    assert names == {"service_status", "get_metrics", "search_logs", "recent_deploys",
                     "get_config", "search_runbooks"}
    assert not names & {"rollback_deploy", "restart_service", "scale_service", "set_config"}

    result = await server.call_tool("search_logs", {"service": "checkout", "level": "ERROR"})
    assert "pool exhausted" in str(result)
