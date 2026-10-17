"""MCP server: what an agent (Claude Code, Claude Desktop, Cursor...) connects to."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .gateway import Gateway, format_outcome

INSTRUCTIONS = (
    "SQL access to the user's analytics database through tollgate. "
    "Pass a short `task` label naming the user question you are working on (for example "
    "'revenue-by-region'), and reuse the same label for every call that serves that question. "
    "Queries are priced like BigQuery: you pay for every column you reference across the whole "
    "table, and LIMIT does not reduce cost. Select only the columns you need."
)


def build_server(gateway: Gateway) -> MCPServer:
    server = MCPServer("tollgate", instructions=INSTRUCTIONS)

    @server.tool()
    def list_tables(task: str) -> str:
        """List the tables in the database with their approximate row counts."""
        gateway.note(task, "list_tables", "")
        rows = gateway.engine.list_tables()
        return "\n".join(f"{name}\t~{n:,} rows" for name, n in rows) or "(no tables)"

    @server.tool()
    def describe_table(table: str, task: str) -> str:
        """Show a table's columns and types."""
        gateway.note(task, "describe_table", table)
        try:
            cols = gateway.engine.describe(table)
        except ValueError as e:
            return f"ERROR: {e}"
        return "\n".join(f"{name}\t{dtype}" for name, dtype in cols)

    @server.tool()
    def run_query(sql: str, task: str) -> str:
        """Run a read-only SQL query (DuckDB dialect) and return up to 100 rows."""
        return format_outcome(gateway.query(sql, task))

    return server
