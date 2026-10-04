"""Unit and contract tests for the 3-Tier Agency architecture (Chat, Agent, Jaeger)."""
from __future__ import annotations

import pathlib
import pytest
from pydantic import ValidationError

from jaeger_ai.contract.modes import (
    DEFAULT_INTERACTION_TIER,
    INTERACTION_TIERS,
    TIER_DESCRIPTIONS,
    TIER_NAMES,
    TIER_NUMBERS,
    InteractionTier,
)
from jaeger_ai.core.instance.schemas import AutomationConfig, Config, ModelConfig, dump_yaml, load_yaml
from jaeger_ai.core.settings.catalog import describe


def test_interaction_tiers_contract() -> None:
    """The canonical contract defines chat=1, agent=2, jaeger=3."""
    assert INTERACTION_TIERS == ("chat", "agent", "jaeger")
    assert DEFAULT_INTERACTION_TIER == "agent"
    assert TIER_NUMBERS["chat"] == 1
    assert TIER_NUMBERS["agent"] == 2
    assert TIER_NUMBERS["jaeger"] == 3
    assert TIER_NAMES[1] == "chat"
    assert TIER_NAMES[2] == "agent"
    assert TIER_NAMES[3] == "jaeger"
    for t in INTERACTION_TIERS:
        assert t in TIER_DESCRIPTIONS
        assert len(TIER_DESCRIPTIONS[t]) > 10


def test_automation_config_interaction_tier_schema() -> None:
    """AutomationConfig defaults to 'agent' and validates allowable tiers."""
    cfg = AutomationConfig()
    assert cfg.interaction_tier == "agent"
    assert cfg.autonomy == "scoped"  # Constitution invariant 11: scoped, not auto

    cfg_chat = AutomationConfig(interaction_tier="chat")
    assert cfg_chat.interaction_tier == "chat"

    cfg_jaeger = AutomationConfig(interaction_tier="jaeger")
    assert cfg_jaeger.interaction_tier == "jaeger"

    with pytest.raises(ValidationError):
        AutomationConfig(interaction_tier="droid")  # forbidden string


def test_settings_catalog_derives_interaction_tier(tmp_path: pathlib.Path) -> None:
    """Single-source derivation: the settings catalog exposes automation.interaction_tier automatically."""
    class _Layout:
        def __init__(self, p: pathlib.Path) -> None:
            self.config_path = p

    cfg_path = tmp_path / "config.yaml"
    dump_yaml(cfg_path, Config(instance_name="test-inst", model=ModelConfig(model_path="/dev/null")))

    desc = describe(_Layout(cfg_path), "automation.interaction_tier")
    assert desc is not None
    assert desc["type"] == "enum"
    assert desc["group"] == "autonomy"
    assert desc["default"] == "agent"
    assert desc["current"] == "agent"
    assert desc["choices"] == ["chat", "agent", "jaeger"]
    assert "Agency tier:" in desc["description"]


def test_interaction_tier_admission_snapshot(tmp_path: pathlib.Path) -> None:
    """GatewaySessionStore normalizes and freezes interaction_tier into execution snapshot."""
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore(tmp_path / "gateway_sessions.sqlite3")

    # Explicit chat tier
    req_chat = store.admit_request(
        "sess-1", "hello world", request_id="req-1",
        requested={"interaction_tier": "chat"},
    )
    assert req_chat["accepted"]
    assert req_chat["execution"]["interaction_tier"] == "chat"

    # Replay preserves the snapshot
    replay = store.admit_request(
        "sess-1", "hello world", request_id="req-1",
        requested={"interaction_tier": "chat"},
    )
    assert replay["replayed"]
    assert replay["execution"]["interaction_tier"] == "chat"

    # Invalid tier rejected on admission
    with pytest.raises(ValueError, match="interaction_tier must be one of"):
        store.admit_request("sess-1", "another", request_id="req-bad", requested={"interaction_tier": "cyborg"})


@pytest.mark.asyncio
async def test_gateway_tier_enforcement_and_events(tmp_path: pathlib.Path) -> None:
    """The Gateway enforces interaction tiers: gating background turns, task creation, and broadcasting events."""
    from unittest.mock import AsyncMock, MagicMock
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from aiohttp.test_utils import make_mocked_request

    cfg_path = tmp_path / "config.yaml"
    dump_yaml(cfg_path, Config(instance_name="test-inst", model=ModelConfig(model_path="/dev/null")))

    store = GatewaySessionStore(tmp_path / "gateway_sessions.sqlite3")
    gw = JaegerGatewayApp(store=store)
    gw._config_path = lambda: cfg_path  # point to temp config

    # Default is agent tier
    assert gw._current_tier() == "agent"

    # In Agent mode, proactive background turns are rejected
    bg_result = await gw._run_background_turn("proactive prompt", session_id="s1", request_id="r1", source="sensor")
    assert bg_result["status"] == "disabled"
    assert "requires 'jaeger' mode" in bg_result["error"]

    # Switch to Jaeger mode via handle_set_tier
    events = []
    gw.event_bus.publish = lambda sid, evt, data: events.append((sid, evt, data))

    req = make_mocked_request("POST", "/v1/runtime/tier")
    req.json = AsyncMock(return_value={"tier": "jaeger"})
    resp = await gw.handle_set_tier(req)
    assert resp.status == 200
    assert gw._current_tier() == "jaeger"
    assert any(evt == "runtime.tier.changed" and data.get("tier") == "jaeger" for _, evt, data in events)

    # In Jaeger mode, background turns are accepted into admission and executed
    gw._execute_turn = AsyncMock()
    bg_result_jaeger = await gw._run_background_turn("proactive prompt", session_id="s1", request_id="r2", source="sensor")
    assert gw._execute_turn.await_count == 1

    # Switch to Chat mode
    req.json = AsyncMock(return_value={"tier": "chat"})
    await gw.handle_set_tier(req)
    assert gw._current_tier() == "chat"

    # In Chat mode, task submission is disabled
    req_task = make_mocked_request("POST", "/v1/tasks")
    req_task.json = AsyncMock(return_value={"session_id": "s1", "goal": "do work"})
    resp_task = await gw.handle_tasks(req_task)
    assert resp_task.status == 403

    # In Chat mode, orchestration task creation is disabled
    req_orch = make_mocked_request("POST", "/v1/orchestration/tasks")
    resp_orch = await gw.handle_create_orchestration_task(req_orch)
    assert resp_orch.status == 403


@pytest.mark.asyncio
async def test_chat_tier_enforces_model_only_lane(tmp_path: pathlib.Path) -> None:
    """In Chat tier, turns are strictly conversational (model-only lane) and never invoke tool ReAct."""
    from unittest.mock import AsyncMock, patch
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore(tmp_path / "gateway_sessions.sqlite3")
    gw = JaegerGatewayApp(store=store)

    # Admit turn with explicit chat tier
    admitted = store.admit_request(
        "sess-chat", "Can you edit my file please?", request_id="req-chat-1",
        requested={"interaction_tier": "chat"},
    )
    assert admitted["execution"]["interaction_tier"] == "chat"

    # Mock ollama_chat to return a conversational response
    gw._ollama_chat = AsyncMock(return_value="I am in Chat mode and cannot run tools.")
    react_mock = AsyncMock()
    gw._continued_owner_react = react_mock

    # Execute the turn
    await gw._execute_turn(
        "sess-chat",
        admitted["turn_id"],
        "Can you edit my file please?",
        request_id="req-chat-1",
        execution=admitted["execution"],
    )

    # _ollama_chat was invoked for pure conversational answer
    assert gw._ollama_chat.await_count == 1
    # ReAct / tool execution was NEVER called
    assert react_mock.await_count == 0


