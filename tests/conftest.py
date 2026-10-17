import duckdb
import pytest

from tollgate.engine import DuckDBEngine
from tollgate.gateway import Gateway, QueryLog


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.duckdb"
    con = duckdb.connect(str(path))
    # big: ~1M rows so column sizes exceed BigQuery's 10 MB per-table minimum
    con.execute("""
        CREATE TABLE big AS
        SELECT range AS a, range * 2 AS b, 'item-' || range AS s
        FROM range(1000000)
    """)
    con.execute("CREATE TABLE small (id INTEGER, name VARCHAR)")
    con.execute("INSERT INTO small VALUES (1, 'ab'), (2, NULL)")
    con.close()
    return str(path)


@pytest.fixture
def engine(db_path):
    return DuckDBEngine(db_path)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_gateway(engine, tmp_path, clock):
    def make(**kw):
        return Gateway(engine, QueryLog(tmp_path / "log.jsonl"), clock=clock, **kw)
    return make
