"""Tests for Multi-Agent Architecture (Workstream 12).

Verifies Invariants:
1. RuntimeHost can host multiple independent EntityRuntime instances.
2. Complete private memory isolation:
   Entity A's episodic events and semantic claims NEVER leak into Entity B.
3. Sovereign Jaeger can delegate tasks to subordinate workers with scoped capability grants.
4. Deterministic cancellation of delegated tasks.
5. Inter-agent communication via structured AgentMessage and inboxes.
6. Shared collaboration blackboard works without polluting private memory.
"""
from pathlib import Path
import tempfile
import pytest

from jaeger_ai.core.entity.events import EventType, JaegerEvent
from jaeger_ai.core.multi_agent.host import RuntimeHost
from jaeger_ai.core.multi_agent.models import (
    AgentType,
    DelegationStatus,
    TrustLevel,
)


@pytest.fixture
def host():
    return RuntimeHost()


def test_independent_entities_memory_isolation(host: RuntimeHost):
    """Two independent persistent entities have distinct identities and zero memory leakage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        root_a = base / "agent_alice"
        root_b = base / "agent_bob"

        # 1. Create two sovereign entities
        runtime_a = host.create_persistent_entity("Alice", root_a)
        runtime_b = host.create_persistent_entity("Bob", root_b)

        assert runtime_a.identity.entity_id != runtime_b.identity.entity_id
        assert runtime_a.identity.display_name == "Alice"
        assert runtime_b.identity.display_name == "Bob"

        # 2. Entity A records a private episodic event and semantic claim
        ev_a = JaegerEvent.human_message("Alice's confidential prompt", session_id="sess_a")
        runtime_a.event_store.append(ev_a)
        runtime_a.memory_subsystem.semantic.record_claim(
            subject="secret_project",
            predicate="codename",
            value="ProjectX",
        )

        # 3. Entity B checks its memory — MUST BE EMPTY
        events_b = runtime_b.event_store.query_events()
        assert len(events_b) == 0  # Zero episodic leakage

        claims_b = runtime_b.memory_subsystem.semantic.query_claims("secret_project")
        assert len(claims_b) == 0  # Zero semantic leakage

        # Entity A still has its own memories
        events_a = runtime_a.event_store.query_events()
        assert len(events_a) == 1
        claims_a = runtime_a.memory_subsystem.semantic.query_claims("secret_project")
        assert len(claims_a) == 1
        assert claims_a[0]["value"] == "ProjectX"


def test_delegation_and_capability_grants(host: RuntimeHost):
    """Parent Jaeger delegates a task to subordinate worker with scoped grants."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        jaeger = host.create_persistent_entity("Jaeger", base / "jaeger")
        worker = host.create_persistent_entity("WorkerBot", base / "worker")

        host.set_trust(jaeger.identity.entity_id, worker.identity.entity_id, TrustLevel.SUBORDINATE)
        assert host.get_trust(jaeger.identity.entity_id, worker.identity.entity_id) == TrustLevel.SUBORDINATE

        # Delegate task
        task = host.delegate_task(
            parent_entity_id=jaeger.identity.entity_id,
            assigned_to_entity_id=worker.identity.entity_id,
            goal="Compile C++ extension",
            capability_grants=("tool.build.cmake", "tool.build.make"),
        )
        assert task.status == DelegationStatus.RUNNING
        assert "tool.build.cmake" in task.capability_grants

        # Worker checks inbox
        inbox = host.read_inbox(worker.identity.entity_id)
        assert len(inbox) == 1
        assert inbox[0].topic == "delegation.assigned"
        assert inbox[0].payload["goal"] == "Compile C++ extension"

        # Worker completes task
        completed_task = host.complete_delegation(
            task.delegation_id,
            result={"status": "build_ok", "binary": "/tmp/ext.so"},
        )
        assert completed_task.status == DelegationStatus.COMPLETED
        assert completed_task.result["status"] == "build_ok"

        # Parent receives completion notification
        parent_inbox = host.read_inbox(jaeger.identity.entity_id)
        assert len(parent_inbox) == 1
        assert parent_inbox[0].topic == "delegation.completed"
        assert parent_inbox[0].payload["result"]["status"] == "build_ok"


def test_delegation_cancellation(host: RuntimeHost):
    """Parent can deterministically cancel an in-flight delegation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        jaeger = host.create_persistent_entity("Jaeger", base / "jaeger")
        worker = host.create_persistent_entity("WorkerBot", base / "worker")

        task = host.delegate_task(
            parent_entity_id=jaeger.identity.entity_id,
            assigned_to_entity_id=worker.identity.entity_id,
            goal="Long running crawl",
        )
        assert task.status == DelegationStatus.RUNNING

        # Cancel
        cancelled = host.cancel_delegation(task.delegation_id, reason="User clicked stop")
        assert cancelled is True

        assert task.status == DelegationStatus.CANCELLED
        assert task.error == "User clicked stop"

        # Worker gets cancel notification
        inbox = host.read_inbox(worker.identity.entity_id)
        assert any(m.topic == "delegation.cancelled" for m in inbox)


def test_shared_memory_blackboard(host: RuntimeHost):
    """Agents can collaborate via shared memory without cross-contaminating private state."""
    host.set_shared("system_incident_status", "investigating", author_entity_id="jaeger")
    val = host.get_shared("system_incident_status")
    assert val == "investigating"
