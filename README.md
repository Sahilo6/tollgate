# tollgate

**See what each AI agent question costs on your warehouse, catch the wasted queries, and cap the spend.**

AI agents that query data are sloppy. They peek at tables, retry after errors, and run the same query
again. On BigQuery you pay for every column you touch across the whole table, so
`SELECT * FROM events LIMIT 5` costs the same as reading the entire table. Nobody sees this until the bill.

tollgate is an MCP server that sits between the agent and the database:

- **Prices every query** before it runs (BigQuery on-demand rules).
- **Labels it:** `answer`, `schema` lookup, `peek`, `duplicate`, `failed`, or `blocked`.
- **Caches duplicates**, so the second identical query costs $0.
- **Enforces a budget per agent task**, and tells the agent why it was blocked so it can write a cheaper query.
- **Reports** cost and waste per task.

```
task                  calls   answer  schema  peek  duplicate  failed  blocked     cost   waste
revenue-by-region         7        1       2     2          1       1        0  $0.0104     84%
top-customers             3        2       0     1          0       0        0  $0.0064      2%

Waste (peeks + duplicates):  $0.0089  (53% of spend)
Projection at 1,000 questions/day on this data size: $252/month, of which $133/month is waste.
```

Status: early. Works with DuckDB today, and estimates what the same queries would cost on BigQuery.
Real BigQuery and Snowflake connections are next.

## Quickstart

```bash
git clone <this repo> && cd tollgate
uv venv && uv pip install -e ".[dev]"        # or: python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/tollgate demo-data --out demo.duckdb   # TPC-H sample data, about 250 MB, takes ~15 s
```

### Connect it to Claude Code

Create `.mcp.json` in the folder you open Claude Code in (use absolute paths):

```json
{
  "mcpServers": {
    "tollgate": {
      "command": "/path/to/tollgate/.venv/bin/tollgate",
      "args": ["serve", "--db", "/path/to/tollgate/demo.duckdb",
               "--log", "/path/to/tollgate/tollgate-log.jsonl", "--budget-usd", "0.005"]
    }
  }
}
```

Claude Code asks you to approve the server the first time. For Claude Desktop, put the same
`mcpServers` block in `~/Library/Application Support/Claude/claude_desktop_config.json`.

Then ask a question about the data, for example *"Which region has the highest revenue?"*, and run:

```bash
.venv/bin/tollgate report --log tollgate-log.jsonl
```

### Options

| Command | What it does |
|---|---|
| `tollgate serve --db FILE` | Run the MCP server over stdio |
| `--budget-usd 0.01` | Max estimated spend per agent task (off by default) |
| `--cache-ttl 300` | Seconds to reuse a query's result |
| `--log FILE` | Where to write the query log (JSONL) |
| `tollgate report --questions-per-day 1000` | Cost and waste per task, plus a monthly projection |

## How the cost is estimated

BigQuery on-demand bills **$6.25 per TiB** of data processed, where "processed" means the full size of
every column the query references, in every table it reads, with a **10 MB minimum per table**.
`LIMIT` does not reduce it. tollgate computes each column's size the way BigQuery does (8 bytes per
number or date, string bytes + 2, and so on) and prices each query from that.
Sources: [pricing](https://cloud.google.com/bigquery/pricing#on_demand_pricing),
[data type sizes](https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types).

## Development

```bash
.venv/bin/python -m pytest -q
```

Code map: `engine.py` (DuckDB), `cost.py` (BigQuery pricing), `classify.py` (labels),
`gateway.py` (cache, budget, log), `server.py` (MCP tools), `report.py`, `cli.py`.
