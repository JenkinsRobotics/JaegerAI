"""Store transactions must release file descriptors without waiting for GC."""
import sqlite3

import pytest

from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.features.backlog.store import BacklogStore


@pytest.mark.parametrize("kind", ["gateway", "backlog"])
@pytest.mark.parametrize("fail", [False, True])
def test_store_transaction_closes_and_preserves_atomicity(tmp_path, kind, fail):
    store = GatewaySessionStore(tmp_path / "sessions.db") if kind == "gateway" else BacklogStore(tmp_path / "backlog.db")
    connect = store._get_conn if kind == "gateway" else store._conn
    with connect() as setup:
        setup.execute("CREATE TABLE lifetime_probe (value INTEGER)")
    connection = connect()
    try:
        with connection:
            connection.execute("INSERT INTO lifetime_probe VALUES (1)")
            if fail:
                raise ValueError("rollback probe")
    except ValueError:
        pass
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with connect() as check:
        assert check.execute("SELECT COUNT(*) FROM lifetime_probe").fetchone()[0] == (0 if fail else 1)
