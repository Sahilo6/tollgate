"""tollgate command line: demo-data, serve, report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_LOG = "tollgate-log.jsonl"


def cmd_demo_data(args: argparse.Namespace) -> None:
    import duckdb

    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} already exists; delete it first or pick another --out")
    con = duckdb.connect(str(out))
    con.execute("INSTALL tpch; LOAD tpch;")
    con.execute(f"CALL dbgen(sf={args.sf})")
    tables = con.execute("SELECT table_name, estimated_size FROM duckdb_tables() ORDER BY 2 DESC").fetchall()
    con.close()
    print(f"wrote {out} (TPC-H scale factor {args.sf})")
    for name, n in tables:
        print(f"  {name:<10} ~{n:,} rows")


def cmd_serve(args: argparse.Namespace) -> None:
    from .engine import DuckDBEngine
    from .gateway import Gateway, QueryLog
    from .server import build_server

    engine = DuckDBEngine(args.db)
    engine.column_sizes()  # price every column up front so the first query isn't slow
    gateway = Gateway(engine, QueryLog(args.log), budget_usd=args.budget_usd, cache_ttl_s=args.cache_ttl)
    build_server(gateway).run("stdio")


def cmd_report(args: argparse.Namespace) -> None:
    from .report import load, render

    print(render(load(args.log), questions_per_day=args.questions_per_day))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="tollgate", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo-data", help="generate a TPC-H sample database in DuckDB")
    d.add_argument("--out", default="demo.duckdb")
    d.add_argument("--sf", type=float, default=1, help="TPC-H scale factor (1 is about 1 GB)")
    d.set_defaults(func=cmd_demo_data)

    s = sub.add_parser("serve", help="run the MCP server (stdio) in front of a DuckDB file")
    s.add_argument("--db", required=True)
    s.add_argument("--log", default=DEFAULT_LOG)
    s.add_argument("--budget-usd", type=float, default=None, help="max estimated spend per task")
    s.add_argument("--cache-ttl", type=float, default=300, help="seconds to reuse a query's result")
    s.set_defaults(func=cmd_serve)

    r = sub.add_parser("report", help="cost and waste per agent task")
    r.add_argument("--log", default=DEFAULT_LOG)
    r.add_argument("--questions-per-day", type=int, default=1000)
    r.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
