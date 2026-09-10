"""Direct tests for the unified jaeger_ai.features.dispatcher package."""
from jaeger_ai.features.dispatcher import (
    DispatcherStore,
    DISPATCHER,
    FOCUS_PREFIX,
    FOCUS_CONTEXT,
    TOOLSETS,
    task_kind,
    PRIMARY_SESSIONS,
    is_primary_session,
    normalize_session_key,
    prepare_turn_text,
    EXTENSION_ID,
    SidecarHandler,
    run_sidecar,
)


def test_dispatcher_feature_exports():
    assert DispatcherStore is not None
    assert DISPATCHER == "dispatcher"
    assert FOCUS_PREFIX == "focus:"
    assert FOCUS_CONTEXT == 16384
    assert "coding" in TOOLSETS
    assert task_kind("Please write some Python code") == "coding"
    assert task_kind("Research local LLM models") == "research"
    assert is_primary_session("main")
    assert is_primary_session("cli")
    assert not is_primary_session("delegate:worker-1")
    assert normalize_session_key("main", default="cli") == "cli"
    assert normalize_session_key("my-session", default="cli") == "my-session"
    assert EXTENSION_ID == "jaeger-dispatcher"
    assert callable(run_sidecar)
