"""Fingerprint SQL and label what kind of query an agent just ran."""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

DIALECT = "duckdb"

# Labels, in the order the report shows them.
SCHEMA = "schema"        # looking up tables or columns
PEEK = "peek"            # SELECT * ... LIMIT n with no filter: pays for the whole table to see a few rows
DUPLICATE = "duplicate"  # same query already answered earlier in this task
FAILED = "failed"        # the database rejected it
BLOCKED = "blocked"      # tollgate refused it (over budget)
ANSWER = "answer"        # everything else: the queries that actually answer the question

WASTE_KINDS = (PEEK, DUPLICATE)
PEEK_MAX_ROWS = 100
METADATA_KEYWORDS = ("DESCRIBE", "SHOW", "PRAGMA", "SUMMARIZE")
METADATA_SCHEMAS = ("information_schema", "pg_catalog")


def parse(sql: str) -> exp.Expression | None:
    try:
        return sqlglot.parse_one(sql.strip().rstrip(";"), read=DIALECT)
    except sqlglot.errors.ParseError:
        return None


def fingerprint(sql: str, tree: exp.Expression | None = None) -> str:
    """Same text for queries that differ only in case, spacing or a trailing semicolon."""
    tree = tree if tree is not None else parse(sql)
    if tree is None:
        return " ".join(sql.lower().rstrip(";").split())
    return normalize_identifiers(tree.copy(), dialect=DIALECT).sql(dialect=DIALECT)


def is_metadata(sql: str, tree: exp.Expression | None) -> bool:
    first = sql.strip().split(None, 1)[0].upper() if sql.strip() else ""
    if first in METADATA_KEYWORDS:
        return True
    if tree is None:
        return False
    for table in tree.find_all(exp.Table):
        if table.db.lower() in METADATA_SCHEMAS or table.name.lower().startswith("duckdb_"):
            return True
    for fn in tree.find_all(exp.Anonymous):  # table functions like duckdb_tables()
        if fn.name.lower().startswith(("duckdb_", "pragma_")):
            return True
    return False


# Clauses that narrow or reshape a scan. sqlglot renamed some keys over versions ("with" -> "with_").
NARROWING_ARGS = ("where", "group", "having", "joins", "with", "with_", "qualify", "sample")


def is_peek(tree: exp.Expression | None) -> bool:
    """SELECT * (or t.*) from one table with a small LIMIT and nothing that narrows the scan."""
    if not isinstance(tree, exp.Select):
        return False
    limit = tree.args.get("limit")
    if limit is None:
        return False
    n = limit.args.get("expression")
    if not isinstance(n, exp.Literal) or n.is_string or int(n.this) > PEEK_MAX_ROWS:
        return False
    if any(tree.args.get(k) for k in NARROWING_ARGS):
        return False
    selects_star = any(
        isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
        for e in tree.expressions
    )
    return selects_star


def classify(sql: str, tree: exp.Expression | None, fp: str, seen_in_task: set[str]) -> str:
    """Label a query before it runs. FAILED and BLOCKED are decided by the gateway."""
    if is_metadata(sql, tree):
        return SCHEMA
    if fp in seen_in_task:
        return DUPLICATE
    if is_peek(tree):
        return PEEK
    return ANSWER
