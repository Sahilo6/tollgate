import anyio
from mcp import Client

from tollgate.server import build_server


def call(server, tool, args):
    async def go():
        async with Client(server) as client:
            result = await client.call_tool(tool, args)
            return result.content[0].text
    return anyio.run(go)


def test_tools_over_mcp(make_gateway):
    server = build_server(make_gateway())
    assert "big" in call(server, "list_tables", {"task": "q1"})
    assert "VARCHAR" in call(server, "describe_table", {"table": "big", "task": "q1"})
    out = call(server, "run_query", {"sql": "SELECT a FROM big WHERE a < 2", "task": "q1"})
    assert out.splitlines()[:3] == ["a", "0", "1"]
    assert "[tollgate] scanned" in out


def test_unknown_table(make_gateway):
    server = build_server(make_gateway())
    assert call(server, "describe_table", {"table": "nope", "task": "q1"}).startswith("ERROR")
