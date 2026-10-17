"""Database backends. Only DuckDB for now; BigQuery comes next."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

# BigQuery's logical size per value, used to estimate what a query would be billed.
# https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types (Data type sizes)
FIXED_WIDTH_BYTES = {
    "BOOLEAN": 1,
    "TINYINT": 8, "SMALLINT": 8, "INTEGER": 8, "BIGINT": 8, "HUGEINT": 16,
    "UTINYINT": 8, "USMALLINT": 8, "UINTEGER": 8, "UBIGINT": 8,
    "FLOAT": 8, "DOUBLE": 8,
    "DATE": 8, "TIME": 8, "TIMESTAMP": 8, "TIMESTAMP WITH TIME ZONE": 8, "INTERVAL": 16,
    "UUID": 16,
}
STRING_TYPES = ("VARCHAR", "BLOB")


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool


class DuckDBEngine:
    def __init__(self, path: str):
        self.path = path
        self.con = duckdb.connect(path, read_only=True)
        self._sizes: dict[str, dict[str, int]] | None = None

    def execute(self, sql: str, max_rows: int = 100) -> QueryResult:
        cur = self.con.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows + 1) if columns else []
        return QueryResult(columns, rows[:max_rows], truncated=len(rows) > max_rows)

    def list_tables(self) -> list[tuple[str, int]]:
        return self.con.execute(
            "SELECT table_name, estimated_size FROM duckdb_tables() ORDER BY table_name"
        ).fetchall()

    def describe(self, table: str) -> list[tuple[str, str]]:
        rows = self.con.execute(
            "SELECT column_name, data_type FROM duckdb_columns() "
            "WHERE table_name = ? ORDER BY column_index",
            [table],
        ).fetchall()
        if not rows:
            raise ValueError(f"no table named {table!r}")
        return rows

    def column_sizes(self) -> dict[str, dict[str, int]]:
        """Bytes per column as BigQuery would count them. Computed once, then cached."""
        if self._sizes is None:
            self._sizes = {}
            for table, _ in self.list_tables():
                self._sizes[table] = self._table_column_sizes(table)
        return self._sizes

    def _table_column_sizes(self, table: str) -> dict[str, int]:
        parts, names = [], []
        for col, dtype in self.describe(table):
            q = f'"{col}"'
            base = dtype.split("(")[0].upper()
            if base in STRING_TYPES:
                parts.append(f"coalesce(sum(octet_length({q}::BLOB)), 0) + 2 * count({q})")
            elif base == "DECIMAL":
                parts.append(f"16 * count({q})")
            else:
                parts.append(f"{FIXED_WIDTH_BYTES.get(base, 8)} * count({q})")
            names.append(col)
        values = self.con.execute(f'SELECT {", ".join(parts)} FROM "{table}"').fetchone()
        return {name: int(v) for name, v in zip(names, values)}
