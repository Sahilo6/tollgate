"""Turn the query log into a cost and waste report."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import classify as k

KIND_ORDER = (k.ANSWER, k.SCHEMA, k.PEEK, k.DUPLICATE, k.FAILED, k.BLOCKED)


@dataclass
class TaskSummary:
    task: str
    calls: int = 0
    kinds: dict[str, int] = field(default_factory=dict)
    would_usd: float = 0.0   # what these queries cost with no gateway in front
    paid_usd: float = 0.0    # what they cost with tollgate
    waste_usd: float = 0.0   # peeks and duplicates, priced as if they had run
    saved_usd: float = 0.0   # cache hits and blocked queries

    @property
    def waste_pct(self) -> float:
        return 100 * self.waste_usd / self.would_usd if self.would_usd else 0.0


def load(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize(records: list[dict]) -> tuple[list[TaskSummary], TaskSummary]:
    tasks: dict[str, TaskSummary] = {}
    total = TaskSummary("TOTAL")
    for r in records:
        for s in (tasks.setdefault(r["task"], TaskSummary(r["task"])), total):
            s.calls += 1
            s.kinds[r["kind"]] = s.kinds.get(r["kind"], 0) + 1
            est = r.get("est_usd") or 0.0
            if r["kind"] != k.FAILED:  # BigQuery doesn't bill queries that fail to run
                s.would_usd += est
            s.paid_usd += r.get("paid_usd") or 0.0
            if r["kind"] in k.WASTE_KINDS:
                s.waste_usd += est
            if r.get("cache_hit") or r["kind"] == k.BLOCKED:
                s.saved_usd += est
    return list(tasks.values()), total


def render(records: list[dict], questions_per_day: int = 1000) -> str:
    if not records:
        return "No queries logged yet. Point an agent at `tollgate serve` and ask it something."
    tasks, total = summarize(records)

    head = f"{'task':<28}{'calls':>6}  " + "".join(f"{kd:>10}" for kd in KIND_ORDER) + f"{'cost':>11}{'waste':>8}"
    lines = ["", "tollgate report: cost per agent task (BigQuery on-demand prices)", "", head, "-" * len(head)]
    for s in sorted(tasks, key=lambda s: -s.would_usd):
        lines.append(
            f"{s.task[:27]:<28}{s.calls:>6}  "
            + "".join(f"{s.kinds.get(kd, 0):>10}" for kd in KIND_ORDER)
            + f"{'$' + format(s.would_usd, '.4f'):>11}{format(s.waste_pct, '.0f') + '%':>8}"
        )
    lines.append("-" * len(head))

    n = len(tasks)
    per_task = total.would_usd / n
    lines += [
        "",
        f"Tasks: {n}   Queries: {total.calls}   Avg cost per task: ${per_task:.4f}",
        f"Without tollgate:  ${total.would_usd:.4f}",
        f"Waste (peeks + duplicates):  ${total.waste_usd:.4f}  ({total.waste_pct:.0f}% of spend)",
        f"With tollgate:  ${total.paid_usd:.4f}  (saved ${total.saved_usd:.4f} via cache and budget blocks)",
        f"Blocked by budget: {total.kinds.get(k.BLOCKED, 0)}   Failed queries: {total.kinds.get(k.FAILED, 0)}",
        "",
        f"Projection at {questions_per_day:,} questions/day on this data size: "
        f"${per_task * questions_per_day * 30:,.0f}/month, of which "
        f"${total.waste_usd / n * questions_per_day * 30:,.0f}/month is waste.",
        "",
    ]
    return "\n".join(lines)
