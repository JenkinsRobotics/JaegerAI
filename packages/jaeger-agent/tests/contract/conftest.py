"""Fixtures that hand the same contract to every durable-runtime adapter.

The point of parametrising here rather than writing two test modules is
that a rule can then only be implemented once. If SQLite forgets a guard
the in-memory reference enforces, the shared contract fails for SQLite
and names it — which is the failure mode "modular" architectures
usually discover in production instead.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.commitments import InMemoryCommitmentStore
from jaeger_agent.cognition.effects import InMemoryEffectLedger
from jaeger_agent.cognition.runs import InMemoryRunStore
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
from jaeger_agent.memory import sqlite_store


@pytest.fixture
def bound_db(tmp_path):
    """A real state.db at the current schema, closed afterwards."""
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield tmp_path
    finally:
        sqlite_store.close()


@pytest.fixture(params=["memory", "sqlite"])
def run_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryRunStore()
        return
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield SqliteRunStore()
    finally:
        sqlite_store.close()


@pytest.fixture(params=["memory", "sqlite"])
def effect_ledger(request, tmp_path):
    if request.param == "memory":
        yield InMemoryEffectLedger()
        return
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield SqliteEffectLedger()
    finally:
        sqlite_store.close()


@pytest.fixture(params=["memory", "sqlite"])
def commitment_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryCommitmentStore()
        return
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield SqliteCommitmentStore()
    finally:
        sqlite_store.close()
