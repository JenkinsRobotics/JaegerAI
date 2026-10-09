"""The OWNER turn path builds its agent like the CLI session agent does.

Probe on the 2026-10-09 local-capability failures: the Gateway path sent no
system prompt, all 119 tool schemas (~20k tokens) and had no delegate_task.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity import owner_agent
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, ExternalModelConfig, ModelConfig


@pytest.fixture
def layout(tmp_path, monkeypatch):
    lay = InstanceLayout(root=tmp_path / "inst")
    lay.root.mkdir(parents=True)
    lay.ensure_dirs()
    import jaeger_ai.main as main
    monkeypatch.setattr(main, "_pipeline", {})
    owner_agent._reset_for_tests()
    yield lay
    owner_agent._reset_for_tests()


def _cfg(provider="ollama", model="gemma-4-26b:latest"):
    return Config(instance_name="t", model=ModelConfig(model_path="/dev/null"),
                  external_model=ExternalModelConfig(enabled=True, provider=provider, model=model,
                                                     base_url="http://127.0.0.1:9/v1", ctx=32768))


def _client(provider, model):
    return SimpleNamespace(kind="external", provider=provider, model_name=model)


@pytest.mark.parametrize("provider,model,local", [
    ("ollama", "gemma-4-26b:latest", True),
    ("ollama", "glm-5.1:cloud", False),
    ("lmstudio", "qwen3", True),
    ("openai", "gpt-5", False),
    ("anthropic", "claude", False),
])
def test_local_lane_detection(provider, model, local):
    assert owner_agent.is_local_client(_client(provider, model)) is local


def test_in_process_worker_is_local():
    assert owner_agent.is_local_client(SimpleNamespace(kind="local", provider="", model_name="x"))


def test_options_carry_system_prompt_budget_and_artifacts(layout, monkeypatch):
    import jaeger_ai.main as main
    monkeypatch.setattr(main, "_context_budget_for", lambda cfg: (32768, 4096))
    opts = owner_agent.owner_agent_options(layout, _cfg(), _client("ollama", "gemma-4-26b:latest"))
    assert len(opts["system_prompt"]) > 1000
    assert "Three Laws" in opts["system_prompt"] or "LAW" in opts["system_prompt"].upper()
    assert opts["ctx_window"] == 32768 and opts["completion_reserve"] == 4096
    assert opts["artifact_dir"] == layout.logs_dir / "tool_results"
    assert opts["scope_tools"] is True
    # main's tools now resolve in this process (they read these keys).
    assert main._pipeline["layout"] is layout and main._pipeline["system_prompt"] == opts["system_prompt"]


def test_cloud_lane_keeps_full_surface(layout, monkeypatch):
    import jaeger_ai.main as main
    monkeypatch.setattr(main, "_context_budget_for", lambda cfg: (None, None))
    opts = owner_agent.owner_agent_options(layout, _cfg("openai", "gpt-5"), _client("openai", "gpt-5"))
    assert opts["scope_tools"] is False


def test_full_tools_env_overrides_scoping(layout, monkeypatch):
    import jaeger_ai.main as main
    monkeypatch.setattr(main, "_context_budget_for", lambda cfg: (None, None))
    monkeypatch.setenv("JAEGER_FULL_TOOLS", "1")
    assert owner_agent.owner_agent_options(layout, _cfg(), _client("ollama", "gemma-4-26b:latest"))["scope_tools"] is False


def test_delegate_task_is_registered_and_core(layout, monkeypatch):
    import jaeger_ai.main as main
    from jaeger_agent.skill_registry.toolset_scoping import CORE
    from jaeger_os.core.tools.tool_registry import get_tools
    monkeypatch.setattr(main, "_context_budget_for", lambda cfg: (None, None))
    owner_agent.owner_agent_options(layout, _cfg(), _client("ollama", "gemma-4-26b:latest"))
    names = {t.name for t in get_tools()}
    assert "delegate_task" in names and "delegate_task" in CORE


def test_an_existing_booted_pipeline_is_not_overwritten(layout, monkeypatch):
    import jaeger_ai.main as main
    other = object()
    monkeypatch.setattr(main, "_pipeline", {"layout": other, "system_prompt": "BOOTED"})
    monkeypatch.setattr(main, "_context_budget_for", lambda cfg: (None, None))
    owner_agent.owner_agent_options(layout, _cfg(), _client("ollama", "gemma-4-26b:latest"))
    assert main._pipeline["layout"] is other and main._pipeline["system_prompt"] == "BOOTED"


def test_a_stand_in_layout_is_never_published_process_wide(layout, monkeypatch):
    """A MagicMock layout once leaked into main._pipeline, and the work ledger
    then created '<MagicMock ...run_dir>' directories in the repo root."""
    from unittest.mock import MagicMock

    import jaeger_ai.main as main
    monkeypatch.setattr(owner_agent, "_system_prompt", lambda _main, _layout: "P")
    monkeypatch.setattr(main, "_context_budget_for", lambda cfg: (32768, 4096))
    monkeypatch.setattr(main, "_register_builtins", lambda client: None)
    owner_agent.owner_agent_options(MagicMock(), _cfg(), _client("ollama", "gemma-4-26b:latest"))
    assert "layout" not in main._pipeline


def test_a_stand_in_with_a_real_root_is_still_not_published(layout, monkeypatch):
    """MagicMock(root=<real path>) passed the root-only check; its mock
    identity_path then hung prompt assembly (yaml never reached EOF)."""
    from unittest.mock import MagicMock

    import jaeger_ai.main as main
    monkeypatch.setattr(owner_agent, "_system_prompt", lambda _main, _layout: "P")
    monkeypatch.setattr(main, "_context_budget_for", lambda cfg: (32768, 4096))
    monkeypatch.setattr(main, "_register_builtins", lambda client: None)
    owner_agent.owner_agent_options(MagicMock(root=layout.root), _cfg(), _client("ollama", "gemma-4-26b:latest"))
    assert "layout" not in main._pipeline
