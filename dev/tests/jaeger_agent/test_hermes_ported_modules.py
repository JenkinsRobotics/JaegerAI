"""Unit tests for newly ported Hermes modules in JaegerAI."""

import sqlite3
import pytest
from jaeger_agent.util.trajectory_compressor import (
    CompressionConfig,
    TrajectoryCompressor,
    compress_trajectory_if_needed,
)
from jaeger_agent.memory.sqlite_search import SQLiteSearchEngine, ensure_fts5_schema
from jaeger_agent.background.cron import BackgroundCronScheduler


def test_trajectory_compressor():
    # Build long message history
    messages = [{"role": "system", "content": "You are JaegerAI."}]
    messages.append({"role": "user", "content": "Initial task request"})
    messages.append({"role": "assistant", "content": "Starting work..."})

    # Add 20 intermediate tool execution turns
    for i in range(20):
        messages.append({"role": "tool", "content": f"Tool output log step {i}: " + "x" * 500})

    messages.append({"role": "user", "content": "Final user check"})

    compressor = TrajectoryCompressor(CompressionConfig(target_max_tokens=1000))
    compressed, metrics = compressor.compress(messages, max_tokens=1000)

    assert metrics.was_compressed is True
    assert metrics.turns_removed > 0
    assert len(compressed) < len(messages)
    assert compressed[0]["role"] == "system"


def test_sqlite_search():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE turns (session_id TEXT, role TEXT, content TEXT)")
    conn.execute("INSERT INTO turns VALUES ('s1', 'user', 'How do I deploy Docker containers?')")
    conn.execute("INSERT INTO turns VALUES ('s1', 'assistant', 'Use docker-compose up -d')")

    search_engine = SQLiteSearchEngine(conn)
    results = search_engine.search_turns("Docker")
    assert len(results) >= 1
    assert any("docker" in r["content"].lower() for r in results)




def test_cron_scheduler():
    scheduler = BackgroundCronScheduler()
    job = scheduler.add_job("j1", "Daily Audit", "0 9 * * *", "Run security check")
    assert job.id == "j1"
    assert len(scheduler.list_jobs()) == 1

    removed = scheduler.remove_job("j1")
    assert removed is True
    assert len(scheduler.list_jobs()) == 0
