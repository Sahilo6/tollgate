from tollgate.classify import parse
from tollgate.cost import MIN_BYTES_PER_TABLE, estimate


def est(sql, engine):
    return estimate(parse(sql), engine.column_sizes())


def test_column_sizes_follow_bigquery_rules(engine):
    sizes = engine.column_sizes()
    assert sizes["big"]["a"] == 8 * 1_000_000
    assert sizes["big"]["b"] == 8 * 1_000_000
    # strings: UTF-8 bytes + 2 per value
    expected_s = sum(len(f"item-{i}") + 2 for i in range(1_000_000))
    assert sizes["big"]["s"] == expected_s
    # NULLs cost nothing
    assert sizes["small"]["name"] == len("ab") + 2


def test_pays_only_for_referenced_columns(engine):
    sizes = engine.column_sizes()["big"]
    assert est("SELECT a, b FROM big", engine).bytes == sizes["a"] + sizes["b"]
    assert est("SELECT * FROM big", engine).bytes == sum(sizes.values())


def test_limit_does_not_reduce_cost(engine):
    assert est("SELECT * FROM big LIMIT 5", engine).bytes == est("SELECT * FROM big", engine).bytes


def test_where_columns_count(engine):
    sizes = engine.column_sizes()["big"]
    assert est("SELECT a FROM big WHERE s = 'item-3'", engine).bytes == sizes["a"] + sizes["s"]


def test_ten_mb_minimum_per_table(engine):
    assert est("SELECT name FROM small", engine).bytes == MIN_BYTES_PER_TABLE
    assert est("SELECT count(*) FROM big", engine).bytes == MIN_BYTES_PER_TABLE


def test_aliases_and_joins(engine):
    sizes = engine.column_sizes()
    e = est("SELECT x.a, y.name FROM big x JOIN small y ON x.a = y.id", engine)
    assert e.tables == ["big", "small"]
    assert e.bytes == max(sizes["big"]["a"], MIN_BYTES_PER_TABLE) + MIN_BYTES_PER_TABLE


def test_cte_is_not_billed_as_a_table(engine):
    sizes = engine.column_sizes()["big"]
    e = est("WITH t AS (SELECT a, b FROM big) SELECT * FROM t", engine)
    assert e.tables == ["big"]
    assert e.bytes == sizes["a"] + sizes["b"]


def test_unparseable_sql_has_no_estimate(engine):
    assert est("SELEKT nonsense FROM", engine) is None
