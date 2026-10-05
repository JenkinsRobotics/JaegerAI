"""Phase 1B control-plane proofs against the audit-branch caller model.

These do not open the embodiment gate.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jaeger_ai.core.tasks.completion import CompletionError, authoritative_transition
from jaeger_ai.core.tasks.models import DurableTask, TaskState


def test_completed_verified_requires_evidence():
    task = DurableTask(task_id="t", owning_agent="jaeger", goal="make the file")
    with pytest.raises(CompletionError):
        authoritative_transition(task, TaskState.COMPLETED_VERIFIED, evidence=None)
    with pytest.raises(CompletionError):
        authoritative_transition(task, TaskState.COMPLETED_VERIFIED, evidence="success")
    with pytest.raises(CompletionError):
        authoritative_transition(task, TaskState.COMPLETED, evidence={"path": "x"})
    authoritative_transition(
        task, TaskState.COMPLETED_VERIFIED,
        evidence=[{"path": "/tmp/house.txt", "sha256": "abc"}],
    )
    assert task.state == TaskState.COMPLETED_VERIFIED
    authoritative_transition(task, TaskState.NEEDS_OWNER, evidence=None, error="ask")
    assert task.state == TaskState.NEEDS_OWNER
    authoritative_transition(task, TaskState.BLOCKED, error="waiting")
    assert task.state == TaskState.BLOCKED
