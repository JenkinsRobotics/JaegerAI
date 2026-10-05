"""Phase 1B control-plane proofs against the audit-branch caller model.

These do not open the embodiment gate.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jaeger_ai.core.runtime.webui_bind import webui_bind_host
from jaeger_ai.core.tasks.completion import CompletionError, authoritative_transition
from jaeger_ai.core.tasks.models import DurableTask, TaskState


def test_webui_bind_stays_on_loopback_even_if_host_is_wildcard():
    assert webui_bind_host({"JAEGER_WEBUI_HOST": "0.0.0.0"}) == "127.0.0.1"
    assert webui_bind_host({"JAEGER_WEBUI_ALLOW_LAN": "1", "JAEGER_WEBUI_HOST": "0.0.0.0"}) == "0.0.0.0"


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
