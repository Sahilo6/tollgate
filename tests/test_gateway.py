import json

from tollgate import classify as k
from tollgate.gateway import format_outcome
from tollgate.report import load, render, summarize


def records(gw):
    return [json.loads(line) for line in gw.log.path.read_text().splitlines()]


def test_answer_is_priced_and_logged(make_gateway):
    gw = make_gateway()
    out = gw.query("SELECT a FROM big WHERE a < 3", "t1")
    assert out.kind == k.ANSWER
    assert [r[0] for r in out.result.rows] == [0, 1, 2]
    assert out.estimate.usd > 0
    rec = records(gw)[0]
    assert rec["task"] == "t1" and rec["kind"] == k.ANSWER and rec["paid_usd"] == out.estimate.usd


def test_duplicate_is_served_from_cache_for_free(make_gateway):
    gw = make_gateway()
    first = gw.query("SELECT a FROM big WHERE a < 3", "t1")
    again = gw.query("select A from big where a < 3;", "t1")
    assert again.kind == k.DUPLICATE and again.cache_hit
    assert again.result.rows == first.result.rows
    assert records(gw)[1]["paid_usd"] == 0.0
    assert "served from cache" in format_outcome(again)


def test_cache_expires(make_gateway, clock):
    gw = make_gateway(cache_ttl_s=60)
    gw.query("SELECT a FROM big WHERE a < 3", "t1")
    clock.t = 61
    again = gw.query("SELECT a FROM big WHERE a < 3", "t1")
    assert again.kind == k.DUPLICATE and not again.cache_hit
    assert records(gw)[1]["paid_usd"] > 0  # a duplicate that was paid for again


def test_failed_query_returns_database_error(make_gateway):
    gw = make_gateway()
    out = gw.query("SELECT nope FROM big", "t1")
    assert out.kind == k.FAILED
    assert "nope" in out.error
    assert format_outcome(out).startswith("ERROR:")
    assert records(gw)[0]["paid_usd"] == 0.0


def test_budget_blocks_and_explains(make_gateway):
    gw = make_gateway(budget_usd=0.0001)
    small = gw.query("SELECT a FROM big WHERE a < 3", "t1")  # ~10 MB, about $0.00006
    assert small.kind == k.ANSWER
    blocked = gw.query("SELECT * FROM big", "t1")
    assert blocked.kind == k.BLOCKED
    assert "budget" in format_outcome(blocked)
    # a new task gets its own budget
    assert gw.query("SELECT a FROM big WHERE a < 5", "t2").kind == k.ANSWER


def test_report_counts_waste_and_savings(make_gateway):
    gw = make_gateway()
    gw.note("t1", "list_tables", "")
    gw.query("SELECT * FROM big LIMIT 10", "t1")            # peek: pays for the whole table
    gw.query("SELECT a FROM big WHERE a < 3", "t1")         # answer
    gw.query("SELECT a FROM big WHERE a < 3", "t1")         # duplicate, cached
    gw.query("SELECT nope FROM big", "t1")                  # failed
    tasks, total = summarize(load(gw.log.path))
    assert total.kinds == {k.SCHEMA: 1, k.PEEK: 1, k.ANSWER: 1, k.DUPLICATE: 1, k.FAILED: 1}
    recs = records(gw)
    peek_usd, answer_usd, dup_usd = recs[1]["est_usd"], recs[2]["est_usd"], recs[3]["est_usd"]
    assert total.would_usd == peek_usd + answer_usd + dup_usd
    assert total.waste_usd == peek_usd + dup_usd
    assert total.saved_usd == dup_usd
    assert total.paid_usd == peek_usd + answer_usd
    text = render(load(gw.log.path))
    assert "t1" in text and "Waste" in text and "/month" in text


def test_report_on_empty_log(tmp_path):
    assert "No queries logged" in render(load(tmp_path / "missing.jsonl"))
