"""What is said to the Entity through any client must be findable later.

Live defect (2026-09-21 audit, voice ↔ text continuity): a fact spoken on a
voice session was answered from memory in a typed session as a *stale token
from two days earlier*. The agent's ``search_memory`` index was written only
by the bridge's turn logger, so turns through the Gateway (WebUI, voice, CLI
one-shots) never reached it, and the closest old match won.

Production-path integration: real EntityRuntime, event store and the
jaeger-agent episodic store; only the model is scripted. Embedding search
itself is not exercised — the assertion is that the turn is in the index.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity.runtime import EntityRuntime


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from jaeger_agent.memory import sqlite_store

    state = tmp_path / "state"
    (state / "instances" / "jaeger" / "run").mkdir(parents=True)
    monkeypatch.setenv("JAEGER_STATE_DIR", str(state))
    monkeypatch.setenv("JAEGER_HOME", str(state))
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(state / "instances" / "jaeger"))
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path / "agent_memory"))
    EntityRuntime.reset_singleton()
    yield EntityRuntime(state_root=state)
    EntityRuntime.reset_singleton()


def _episodic_rows():
    from jaeger_agent.memory import sqlite_store

    return sqlite_store.connection().execute(
        "SELECT session_key, user, answer FROM episodic ORDER BY id"
    ).fetchall()


def test_a_gateway_turn_reaches_the_agents_memory_index(runtime):
    reply = "Noted: your voice audit token is ORION-4812."
    runtime.execute_turn(
        "Remember voice audit token ORION-4812",
        session_id="voice-audit",
        source="gateway",
        context={
            "model_runner": lambda t: reply,
            "react_runner": lambda t, session_key="voice-audit": {"text": reply, "tool_activity": []},
        },
    )

    rows = [tuple(r) for r in _episodic_rows()]
    assert ("voice-audit", "Remember voice audit token ORION-4812", reply) in rows


def test_remember_is_not_parsed_into_a_claim_by_regex(runtime):
    """``Remember voice audit token X`` used to store the claim ``voice``."""
    runtime.execute_turn(
        "Remember voice audit token ORION-4812",
        session_id="voice-audit",
        context={
            "model_runner": lambda t: "ok",
            "react_runner": lambda t, session_key="voice-audit": {"text": "ok", "tool_activity": []},
        },
    )

    claims = runtime.memory_subsystem.semantic.list_recent(20)
    assert not any(c.get("predicate") == "remembered_word" for c in claims)


def test_gateway_history_reaches_the_owner_react_runner(runtime):
    marker = f"ORBIT-{uuid.uuid4().hex}"
    prompts: list[str] = []

    def scripted_react(prompt: str, session_key: str = "continuity"):
        prompts.append(prompt)
        return {
            "text": marker if marker in prompt else "MISSING",
            "tool_activity": [],
        }

    result = runtime.execute_turn(
        "What codeword did I give you?",
        session_id="continuity",
        request_id="continuity-2",
        context={
            "gateway_session": {
                "messages": [
                    {"role": "user", "content": f"The codeword is {marker}."},
                    {"role": "assistant", "content": "Stored."},
                    {"role": "user", "content": "What codeword did I give you?"},
                ],
            },
            "react_runner": scripted_react,
            "model_runner": lambda _text: "unused",
        },
    )

    assert result["text"] == marker
    assert marker in prompts[0]
    history, _, current = prompts[0].partition("</conversation_history>")
    history_payload = history.partition("\n\n")[2].strip()
    assert json.loads(history_payload) == [
        {"role": "user", "content": f"The codeword is {marker}."},
        {"role": "assistant", "content": "Stored."},
    ]
    assert current.count("What codeword did I give you?") == 1
