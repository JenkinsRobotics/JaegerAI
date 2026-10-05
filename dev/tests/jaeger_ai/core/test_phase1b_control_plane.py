"""Phase 1B control-plane proofs against the audit-branch caller model.

These do not open the embodiment gate.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.models.ollama_bridge import (
    bridge_authorized,
    bridge_request_allowed,
    daemon_listen,
    proxy_bind_hosts,
)
from jaeger_ai.core.runtime.webui_bind import webui_bind_host
from jaeger_ai.core.tasks.completion import CompletionError, authoritative_transition
from jaeger_ai.core.tasks.models import DurableTask, TaskState


def test_webui_bind_stays_on_loopback_even_if_host_is_wildcard():
    assert webui_bind_host({"JAEGER_WEBUI_HOST": "0.0.0.0"}) == "127.0.0.1"
    assert webui_bind_host({"JAEGER_WEBUI_ALLOW_LAN": "1", "JAEGER_WEBUI_HOST": "0.0.0.0"}) == "0.0.0.0"


def test_ollama_daemon_is_loopback_and_proxy_rejects_lan():
    assert daemon_listen() == "127.0.0.1:11434"
    assert "0.0.0.0" not in proxy_bind_hosts("192.168.64.1")
    assert "0.0.0.0" not in proxy_bind_hosts("0.0.0.0")
    assert bridge_request_allowed(method="POST", path="/api/chat", peer_host="192.168.1.50") is False
    assert bridge_request_allowed(method="DELETE", path="/api/delete", peer_host="127.0.0.1") is False
    assert bridge_request_allowed(method="POST", path="/api/chat", peer_host="192.168.64.2") is True
    assert bridge_authorized("192.168.64.2", None) is False
    token = caller_auth.client_token("mcp")
    assert token
    assert bridge_authorized("192.168.64.2", f"Bearer {token}") is True
    assert bridge_authorized("192.168.64.2", "Bearer not-the-token") is False
    assert bridge_authorized("127.0.0.1", None) is True


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
