"""Estimate what a query would be billed under BigQuery on-demand pricing.

BigQuery charges for every byte of every column a query references, across the whole
table. LIMIT does not reduce the bill, and each referenced table costs at least 10 MB.
https://cloud.google.com/bigquery/pricing#on_demand_pricing
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

USD_PER_TIB = 6.25
MIN_BYTES_PER_TABLE = 10 * 1024**2
TIB = 1024**4

ColumnSizes = dict[str, dict[str, int]]


@dataclass
class Estimate:
    bytes: int
    usd: float
    tables: list[str]


def usd_for_bytes(n: int) -> float:
    return n / TIB * USD_PER_TIB


def referenced_columns(tree: exp.Expression, sizes: ColumnSizes) -> dict[str, set[str]]:
    """Map each real table the query reads to the columns it touches."""
    used: dict[str, set[str]] = {}
    for scope in traverse_scope(tree):
        tables = {
            alias: src.name.lower()
            for alias, src in scope.sources.items()
            if isinstance(src, exp.Table) and src.name.lower() in sizes
        }
        for table in tables.values():
            used.setdefault(table, set())

        select = scope.expression
        if isinstance(select, exp.Select):
            for e in select.expressions:
                if isinstance(e, exp.Star):
                    for table in tables.values():
                        used[table] |= set(sizes[table])
                elif isinstance(e, exp.Column) and isinstance(e.this, exp.Star):
                    table = tables.get(e.table)
                    if table:
                        used[table] |= set(sizes[table])

        for col in scope.columns:
            name = col.name.lower()
            if col.table:
                table = tables.get(col.table)
                if table and name in sizes[table]:
                    used[table].add(name)
            else:
                for table in tables.values():
                    if name in sizes[table]:
                        used[table].add(name)
    return used


def estimate(tree: exp.Expression | None, sizes: ColumnSizes) -> Estimate | None:
    if tree is None:
        return None
    lowered = {t.lower(): {c.lower(): b for c, b in cols.items()} for t, cols in sizes.items()}
    try:
        used = referenced_columns(tree, lowered)
    except Exception:  # sqlglot scope errors on unusual SQL; treat as unknown cost
        return None
    total = 0
    for table, cols in used.items():
        total += max(sum(lowered[table][c] for c in cols), MIN_BYTES_PER_TABLE)
    return Estimate(bytes=total, usd=usd_for_bytes(total), tables=sorted(used))
