"""Unit and integration tests for Workstream 3: Control-Plane Consolidation.

Validates that:
1. Gateway is strictly the control plane (sessions, auth, streaming, requests).
2. EntityRuntime is the sovereign brain and execution engine.
3. Gateway does not directly construct JaegerAgent or independently select cognition.
4. All clients (Gateway, CLI, background) route through canonical EntityRuntime execution.
"""
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.entity.runtime import EntityRuntime, EntityRuntimeMode
from jaeger_ai.core.entity.events import EventType
from jaeger_ai.core.entity.event_store import SqliteEventStore
from jaeger_ai.core.entity.cognition_router import CognitionRouter, CognitiveStrategy


@pytest.fixture
def isolated_entity_runtime(tmp_path: Path):
    """Provide an isolated EntityRuntime singleton for testing."""
    event_store = SqliteEventStore(tmp_path / "events.sqlite3")
    identity = EntityIdentity(
        entity_id="test-control-plane-entity",
        display_name="JaegerTest",
        created_at=1000.0,
        instance_name="jaeger-test",
    )
    with patch.object(EntityRuntime, "_instance", None):
        rt = EntityRuntime(
            state_root=tmp_path,
            event_store=event_store,
            identity=identity,
            mode=EntityRuntimeMode.TEST,
        )
        EntityRuntime._instance = rt
        yield rt
        EntityRuntime._instance = None


def test_gateway_server_does_not_construct_jaeger_agent_directly():
    """Assert Gateway server module does not import or instantiate build_jaeger_agent."""
    server_path = Path("jaeger_ai/core/gateway/server.py")
    source = server_path.read_text(encoding="utf-8")

    assert "build_jaeger_agent(" not in source, (
        "Gateway server must not directly construct JaegerAgent; "
        "turn execution belongs strictly to EntityRuntime"
    )
    assert "from jaeger_agent.loop.runtime_bridge import build_jaeger_agent" not in source, (
        "Gateway server must not import build_jaeger_agent directly"
    )


def test_entity_runtime_owns_subordinate_react(isolated_entity_runtime):
    """Assert EntityRuntime has canonical run_subordinate_react capability."""
    rt = isolated_entity_runtime
    layout_mock = MagicMock()
    layout_mock.data_dir = rt.state_root
    layout_mock.config_path = rt.state_root / "config.yaml"
    layout_mock.workspace_dir = rt.state_root / "workspace"
    layout_mock.root = rt.state_root
    rt.layout = layout_mock

    mock_agent = MagicMock()

    with patch("jaeger_ai.core.instance.schemas.load_yaml") as mock_load_yaml, \
         patch("jaeger_ai.core.models.external_model.ExternalModelClient") as mock_client_cls, \
         patch("jaeger_agent.loop.runtime_bridge.build_jaeger_agent", return_value=mock_agent) as mock_builder, \
         patch("jaeger_agent.cognition.executive.TurnExecutive") as mock_exec_cls, \
         patch("jaeger_agent.cognition.sqlite_runs.SqliteRunStore"), \
         patch("jaeger_agent.cognition.sqlite_commitments.SqliteCommitmentStore"), \
         patch("jaeger_agent.memory.sqlite_store.bind"), \
         patch("jaeger_agent.core.workspace.bind"):

        cfg_mock = MagicMock()
        cfg_mock.external_model.provider = "ollama"
        mock_load_yaml.return_value = cfg_mock

        mock_exec = MagicMock()
        mock_exec.run_turn.return_value = "Subordinate ReAct completed by EntityRuntime"
        mock_exec_cls.return_value = mock_exec

        res = rt.run_subordinate_react(
            "Do a task",
            session_key="test_session",
            request_id="req_123",
        )

        assert res["text"] == "Subordinate ReAct completed by EntityRuntime"
        assert "halt_reason" in res
        mock_builder.assert_called_once()
        mock_exec.run_turn.assert_called_once_with("Do a task")
        state = {}
        mock_builder.reset_mock()
        rt.run_subordinate_react("Inspect once", continuation_state=state)
        mock_agent.messages = [{"role": "tool", "content": "inspection evidence"}]
        rt.run_subordinate_react("Continue implementation", continuation_state=state)
        mock_builder.assert_called_once()
        assert state["agent"] is mock_agent
        assert mock_agent.messages[0]["content"] == "inspection evidence"
        assert mock_agent._skill_route_query == ""



def test_cognition_router_react_handler_defaults_to_runtime_subordinate(isolated_entity_runtime):
    """Assert CognitionRouter ReActHandler invokes EntityRuntime when no custom runner is passed."""
    rt = isolated_entity_runtime
    layout_mock = MagicMock()
    layout_mock.data_dir = rt.state_root
    rt.layout = layout_mock

    router = CognitionRouter()
    mock_event = MagicMock()
    mock_event.event_id = "ev_react_1"
    mock_event.session_id = "test_session"
    mock_event.request_id = "req_react_1"
    mock_event.payload = {"text": "inspect system state"}

    mock_decision = MagicMock()
    mock_decision.strategy = CognitiveStrategy.REACT_LOOP
    mock_decision.refinement_required = False

    with patch.object(rt, "run_subordinate_react",
                      return_value={"text": "Runtime native result", "halt_reason": None}) as mock_sub:
        result = router.execute(
            strategy=CognitiveStrategy.REACT_LOOP,
            event=mock_event,
            decision=mock_decision,
            state=rt.current_state,
            memory=rt.memory_subsystem,
            authority=rt.authority_layer,
            context={"session_id": "test_session"},
        )

        assert result.get("strategy") == CognitiveStrategy.REACT_LOOP.value
        assert result.get("text") == "Runtime native result"
        mock_sub.assert_called_once()


def test_canonical_execute_turn_contract(isolated_entity_runtime):
    """Assert EntityRuntime.execute_turn produces standardized, verified result structure."""
    rt = isolated_entity_runtime

    result = rt.execute_turn(
        "hello Jaeger",
        session_id="session_cp_1",
        request_id="req_cp_1",
        context={"model_runner": lambda p: "Hello from Jaeger persistent runtime!"},
    )

    assert isinstance(result, dict)
    assert result.get("strategy") in {s.value for s in CognitiveStrategy}
    assert "tool_activity" in result
    assert result.get("error") is None
    assert result.get("text") == "Hello from Jaeger persistent runtime!"

    # Verify event was persisted to fabric
    events = rt.event_store.query_events(session_id="session_cp_1")
    assert len(events) >= 2
    types = [e.event_type for e in events]
    assert EventType.HUMAN_MESSAGE.value in types
    assert EventType.AGENT_RESPONSE.value in types


def test_project_write_scope_is_explicit_contained_and_request_local(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import pytest
    from jaeger_agent import workspace

    project = tmp_path / 'project'
    project.mkdir()
    outside = tmp_path / 'other'
    outside.mkdir()
    (project / 'escape').symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(workspace, '_layout', SimpleNamespace(skills_dir=outside, workspace_dir=outside))
    with workspace.project_scope(project):
        assert workspace._resolve_write('new.py') == project / 'new.py'
        assert workspace._resolve_write(str(project / 'new.py')) == project / 'new.py'
        for path in ('../other/new.py', 'escape/new.py', str(outside / 'new.py')):
            with pytest.raises(workspace.SandboxError):
                workspace._resolve_write(path)
    with workspace.project_scope(None):
        assert workspace.get_project_root() is None
