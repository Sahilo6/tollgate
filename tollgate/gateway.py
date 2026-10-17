"""The gateway every agent query goes through: label, price, cache, budget, log."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import classify as k
from .cost import Estimate, estimate
from .engine import DuckDBEngine, QueryResult


@dataclass
class TaskState:
    spent_usd: float = 0.0
    answered: set[str] = field(default_factory=set)  # fingerprints that succeeded in this task


@dataclass
class Outcome:
    kind: str
    result: QueryResult | None = None
    error: str | None = None
    estimate: Estimate | None = None
    cache_hit: bool = False


class QueryLog:
    """Append-only JSONL, one line per call."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


class Gateway:
    def __init__(
        self,
        engine: DuckDBEngine,
        log: QueryLog,
        budget_usd: float | None = None,
        cache_ttl_s: float = 300.0,
        clock=time.monotonic,
    ):
        self.engine = engine
        self.log = log
        self.budget_usd = budget_usd
        self.cache_ttl_s = cache_ttl_s
        self.clock = clock
        self.tasks: dict[str, TaskState] = {}
        self.cache: dict[str, tuple[float, QueryResult]] = {}

    def query(self, sql: str, task: str) -> Outcome:
        started = self.clock()
        state = self.tasks.setdefault(task, TaskState())
        tree = k.parse(sql)
        fp = k.fingerprint(sql, tree)
        kind = k.classify(sql, tree, fp, state.answered)
        est = estimate(tree, self.engine.column_sizes())
        if kind == k.SCHEMA:
            est = None  # metadata lookups are free or nearly free

        cached = self.cache.get(fp)
        if cached and self.clock() - cached[0] <= self.cache_ttl_s:
            out = Outcome(kind, result=cached[1], estimate=est, cache_hit=True)
            return self._finish(task, sql, fp, out, started, paid_usd=0.0)

        cost = est.usd if est else 0.0
        if self.budget_usd is not None and state.spent_usd + cost > self.budget_usd:
            out = Outcome(k.BLOCKED, estimate=est, error=self._budget_message(task, state, est))
            return self._finish(task, sql, fp, out, started, paid_usd=0.0)

        try:
            result = self.engine.execute(sql)
        except Exception as e:  # the database's own error goes back to the agent verbatim
            out = Outcome(k.FAILED, estimate=est, error=str(e).strip())
            return self._finish(task, sql, fp, out, started, paid_usd=0.0)

        state.spent_usd += cost
        state.answered.add(fp)
        if kind != k.SCHEMA:
            self.cache[fp] = (self.clock(), result)
        return self._finish(task, sql, fp, Outcome(kind, result=result, estimate=est), started, paid_usd=cost)

    def note(self, task: str, call: str, detail: str) -> None:
        """Log a non-SQL tool call (list_tables, describe_table) as a schema lookup."""
        self.tasks.setdefault(task, TaskState())
        self.log.write({
            "ts": time.time(), "task": task, "call": call, "sql": detail, "kind": k.SCHEMA,
            "est_bytes": 0, "est_usd": 0.0, "paid_usd": 0.0, "cache_hit": False, "error": None, "ms": 0,
        })

    def _budget_message(self, task: str, state: TaskState, est: Estimate | None) -> str:
        gb = (est.bytes if est else 0) / 1024**3
        return (
            f"tollgate blocked this query: it would scan about {gb:.2f} GB "
            f"(~${est.usd if est else 0:.4f} at BigQuery on-demand rates), and task '{task}' "
            f"has already spent ${state.spent_usd:.4f} of its ${self.budget_usd:.4f} budget. "
            "Select only the columns you need, add a filter, or ask the user to raise the budget."
        )

    def _finish(self, task: str, sql: str, fp: str, out: Outcome, started: float, paid_usd: float) -> Outcome:
        self.log.write({
            "ts": time.time(),
            "task": task,
            "call": "run_query",
            "sql": sql,
            "fingerprint": fp,
            "kind": out.kind,
            "est_bytes": out.estimate.bytes if out.estimate else 0,
            "est_usd": out.estimate.usd if out.estimate else 0.0,
            "paid_usd": paid_usd,
            "cache_hit": out.cache_hit,
            "error": out.error,
            "rows": len(out.result.rows) if out.result else 0,
            "ms": round((self.clock() - started) * 1000, 1),
        })
        return out


def format_outcome(out: Outcome) -> str:
    """What the agent sees: the rows, plus one line about cost."""
    if out.kind == k.BLOCKED:
        return out.error or "tollgate blocked this query."
    if out.error:
        return f"ERROR: {out.error}"
    r = out.result
    lines = ["\t".join(r.columns)] + ["\t".join("" if v is None else str(v) for v in row) for row in r.rows]
    if r.truncated:
        lines.append(f"... (showing first {len(r.rows)} rows)")
    if out.cache_hit:
        lines.append("[tollgate] served from cache: $0.0000 (you already ran this query)")
    elif out.estimate:
        mb = out.estimate.bytes / 1024**2
        lines.append(f"[tollgate] scanned ~{mb:,.0f} MB, ~${out.estimate.usd:.4f} at BigQuery on-demand rates")
    return "\n".join(lines)


__all__ = ["Gateway", "QueryLog", "Outcome", "format_outcome"]
