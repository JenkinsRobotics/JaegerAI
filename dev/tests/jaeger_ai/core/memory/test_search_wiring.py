import sqlite3
from types import SimpleNamespace

from jaeger_agent.memory import sqlite_store
from jaeger_agent.memory.sqlite_search import SQLiteSearchEngine, ensure_fts5_schema


def test_real_schema_search_tracks_updates_deletes_and_reopen(tmp_path):
    conn = sqlite_store._open(tmp_path / 'state.db')
    try:
        sqlite_store._ensure_schema(conn)
        conn.execute("INSERT INTO episodic(session_key, ts, user, answer) VALUES ('a', 'now', 'violet flower', 'purple petals')")
        engine = SQLiteSearchEngine(conn)
        assert engine.fts_active
        assert engine.search_turns('violet')[0]['role'] == 'user'
        assert engine.search_turns('purple', session_id='a')[0]['role'] == 'assistant'
        assert engine.search_turns('purple', session_id='b') == []
        conn.execute("UPDATE episodic SET answer='yellow petals'")
        assert engine.search_turns('purple') == []
        assert engine.search_turns('yellow')
        assert ensure_fts5_schema(conn)
        assert len(engine.search_turns('yellow')) == 1
        engine.fts_active = False
        assert engine.search_turns('yellow')[0]['role'] == 'assistant'
        conn.execute('DELETE FROM episodic')
        engine.fts_active = True
        assert engine.search_turns('yellow') == []
    finally:
        conn.close()


def test_index_initialization_does_not_commit_callers_transaction():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE turns(session_id TEXT, role TEXT, content TEXT)')
    conn.execute("INSERT INTO turns VALUES ('a', 'user', 'violet')")
    assert ensure_fts5_schema(conn)
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM turns').fetchone()[0] == 0
    conn.close()


def test_setup_facts_are_persistent_idempotent_and_do_not_rebind(tmp_path):
    layout = SimpleNamespace(memory_dir=tmp_path / 'memory')
    original = dict(sqlite_store._state)
    sqlite_store.seed_facts(layout, {'name': 'Matthew', 'custom_prime_directive': 'Be useful'})
    sqlite_store.seed_facts(layout, {'name': 'Different'})
    assert sqlite_store._state == original
    with sqlite3.connect(layout.memory_dir / 'state.db') as conn:
        assert dict(conn.execute('SELECT key, value FROM facts')) == {
            'name': 'Matthew', 'custom_prime_directive': 'Be useful'}
        assert conn.execute('SELECT count(*) FROM fact_log').fetchone()[0] == 2
