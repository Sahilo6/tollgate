from tollgate import classify as k


def label(sql, seen=frozenset()):
    tree = k.parse(sql)
    return k.classify(sql, tree, k.fingerprint(sql, tree), set(seen))


def test_fingerprint_ignores_case_spacing_and_semicolon():
    assert k.fingerprint("select  A from   Big;") == k.fingerprint("SELECT a FROM big")


def test_fingerprint_keeps_literals():
    assert k.fingerprint("SELECT a FROM big WHERE a = 1") != k.fingerprint("SELECT a FROM big WHERE a = 2")


def test_schema_lookups():
    for sql in ("DESCRIBE big", "SHOW TABLES", "PRAGMA table_info('big')",
                "SELECT * FROM information_schema.columns", "SELECT * FROM duckdb_tables()"):
        assert label(sql) == k.SCHEMA, sql


def test_peek():
    assert label("SELECT * FROM big LIMIT 10") == k.PEEK
    assert label("select b.* from big b limit 5") == k.PEEK


def test_not_a_peek():
    assert label("SELECT * FROM big WHERE a = 1 LIMIT 10") == k.ANSWER   # filtered
    assert label("SELECT a FROM big LIMIT 10") == k.ANSWER              # one column
    assert label("SELECT * FROM big LIMIT 5000") == k.ANSWER            # big limit
    assert label("SELECT * FROM big") == k.ANSWER
    assert label("WITH t AS (SELECT a FROM big WHERE a < 9) SELECT * FROM t LIMIT 5") == k.ANSWER
    assert label("SELECT * FROM big JOIN small ON a = id LIMIT 5") == k.ANSWER


def test_duplicate_within_task():
    fp = k.fingerprint("SELECT a FROM big")
    assert label("select A from BIG;", seen={fp}) == k.DUPLICATE
