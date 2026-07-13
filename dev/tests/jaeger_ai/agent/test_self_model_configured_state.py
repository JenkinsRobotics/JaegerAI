"""0.9.3 Task 3 — self-model configured-state + app-control awareness.

Covers the three additions to ``build_self_model_block()``:

  (a) messaging configured-state — per-channel status derived from
      autostart membership + credential presence, not just "installed".
  (b) an app-control group (open apps/URLs, drive macOS apps, take
      screenshots) so the id knows it can drive the desktop at all.
  (c) email showing up as a registry-derived group the moment
      ``send_email`` registers (no hand-added line).

And the cache invalidation wiring: an autostart write
(``activate_plugin_inprocess`` → ``_persist_plugin_autostart``) and a
credential save (``set_credential`` tool) both clear
``persona_lane``'s per-boot cache so the next turn sees fresh state.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

import jaeger_ai.main as m
from jaeger_ai.agent import tools
from jaeger_ai.agent.prompts import persona_lane
from jaeger_ai.agent.tools import credentials as creds_tool
from jaeger_ai.core import credentials as creds
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml


def _fresh_instance(autostart: list[str] | None = None) -> InstanceLayout:
    root = pathlib.Path(tempfile.mkdtemp())
    layout = InstanceLayout(root=root)
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    cfg = Config(instance_name="test-instance",
                 model=ModelConfig(model_path=pathlib.Path("stub.gguf")))
    cfg.plugins.autostart = list(autostart or [])
    dump_yaml(layout.config_path, cfg)
    return layout


@pytest.fixture(autouse=True)
def _reset_self_model_cache_around_tests():
    persona_lane.reset_self_model_cache()
    yield
    persona_lane.reset_self_model_cache()


# ── (a) messaging configured-state ────────────────────────────────


def test_messaging_configured_state_active_vs_needs_token_vs_available(monkeypatch):
    """The operator's literal example shape: an autostarted +
    credentialed channel reads active, a credential-less one reads
    needs-token, and a credentialed-but-not-autostarted one reads
    available."""
    layout = _fresh_instance(autostart=["telegram"])
    creds.set_credential(layout, "TELEGRAM_BOT_TOKEN", "tg-token-123")
    # discord: installed, no credential saved.
    # imessage: installed, no token required at all (token=None), not autostarted.
    tools.bind(layout)
    monkeypatch.setattr(
        persona_lane, "_installed_messaging_channels",
        lambda: ["discord", "imessage", "telegram"],
    )
    try:
        line = persona_lane._messaging_configured_state()
    finally:
        tools.bind(_fresh_instance())  # don't leak this test's layout globally

    assert line is not None
    assert "telegram ✓ active" in line
    assert "discord ✗ (needs token)" in line
    assert "imessage ✓ available" in line


def test_messaging_configured_state_none_when_no_channels_installed(monkeypatch):
    monkeypatch.setattr(persona_lane, "_installed_messaging_channels", lambda: [])
    assert persona_lane._messaging_configured_state() is None


def test_messaging_configured_state_falls_back_to_bare_names_without_a_bound_layout(monkeypatch):
    """Never overclaim a status it can't check — with tools unbound, the
    line lists channels without a ✓/✗ suffix rather than guessing."""
    from jaeger_ai.core import context as core_context
    saved = core_context._layout
    core_context._layout = None
    try:
        monkeypatch.setattr(
            persona_lane, "_installed_messaging_channels", lambda: ["telegram"],
        )
        line = persona_lane._messaging_configured_state()
    finally:
        core_context._layout = saved
    assert line == "messaging: telegram"


def test_self_model_block_contains_messaging_configured_state_for_a_fabricated_instance(monkeypatch):
    """End-to-end: build_self_model_block() itself carries the rich
    configured-state line (telegram autostarted+credentialed, discord
    not) — not just the helper function in isolation."""
    layout = _fresh_instance(autostart=["telegram"])
    creds.set_credential(layout, "TELEGRAM_BOT_TOKEN", "tg-token-123")
    tools.bind(layout)
    monkeypatch.setattr(
        persona_lane, "_installed_messaging_channels", lambda: ["discord", "telegram"],
    )
    try:
        block = persona_lane.build_self_model_block()
    finally:
        tools.bind(_fresh_instance())

    assert "telegram ✓ active" in block
    assert "discord ✗ (needs token)" in block


# ── (b) app-control group ─────────────────────────────────────────


def test_app_control_group_present_when_computer_use_is_registered(monkeypatch):
    monkeypatch.setattr(
        persona_lane, "_live_tool_names", lambda: {"computer_use", "get_time"},
    )
    monkeypatch.setattr(persona_lane, "_installed_slots", lambda: set())
    monkeypatch.setattr(persona_lane, "_installed_messaging_channels", lambda: [])
    block = persona_lane.build_self_model_block()
    assert persona_lane._SELF_MODEL_APP_CONTROL_LABEL in block


def test_app_control_group_present_when_only_open_on_host_is_registered(monkeypatch):
    # open_on_host is always-registered even without the macOS computer_use
    # skill loaded — the group must still show for that baseline case.
    monkeypatch.setattr(persona_lane, "_live_tool_names", lambda: {"open_on_host"})
    monkeypatch.setattr(persona_lane, "_installed_slots", lambda: set())
    monkeypatch.setattr(persona_lane, "_installed_messaging_channels", lambda: [])
    block = persona_lane.build_self_model_block()
    assert persona_lane._SELF_MODEL_APP_CONTROL_LABEL in block


def test_app_control_group_absent_when_none_of_its_tools_are_registered(monkeypatch):
    monkeypatch.setattr(persona_lane, "_live_tool_names", lambda: {"get_time"})
    monkeypatch.setattr(persona_lane, "_installed_slots", lambda: set())
    monkeypatch.setattr(persona_lane, "_installed_messaging_channels", lambda: [])
    block = persona_lane.build_self_model_block()
    assert persona_lane._SELF_MODEL_APP_CONTROL_LABEL not in block


# ── 0.9.3 Task 5: unavailable-with-reason instead of a silent omission ──


def test_app_control_shows_unavailable_with_reason_instead_of_silent_omission(monkeypatch):
    """When app-control tools aren't registered, the block explains WHY
    (a skip reason) instead of just dropping the line — the operator's
    ask: "app control: unavailable — <reason>" so the agent can say why,
    not fail mutely on the first attempt."""
    monkeypatch.setattr(persona_lane, "_live_tool_names", lambda: {"get_time"})
    monkeypatch.setattr(persona_lane, "_installed_slots", lambda: set())
    monkeypatch.setattr(persona_lane, "_installed_messaging_channels", lambda: [])
    monkeypatch.setattr(
        persona_lane, "_app_control_unavailable_reason", lambda: "pyobjc missing",
    )
    block = persona_lane.build_self_model_block()
    assert "app control: unavailable — pyobjc missing" in block
    assert persona_lane._SELF_MODEL_APP_CONTROL_LABEL not in block


def test_app_control_unavailable_reason_reads_the_skill_loaders_last_skip(monkeypatch):
    """Wiring check: ``_app_control_unavailable_reason`` asks the skill
    loader for the REAL skip reason (by every plausible app-control
    skill id) rather than inventing its own text — a fabricated failing
    ``macos_computer`` skill's recorded reason flows straight through."""
    from jaeger_ai.agent.skill_registry import skill_loader

    fabricated_reason = ("import/register failed: ModuleNotFoundError: "
                          "No module named 'pyobjc'\ntraceback...")

    def fake_last_skip_reason(*names: str):
        assert "macos_computer" in names  # the real manifest id, not the folder name
        return fabricated_reason

    monkeypatch.setattr(skill_loader, "last_skip_reason", fake_last_skip_reason)
    reason = persona_lane._app_control_unavailable_reason()
    assert reason == "import/register failed: ModuleNotFoundError: No module named 'pyobjc'"


def test_app_control_unavailable_reason_falls_back_when_nothing_was_skipped(monkeypatch):
    from jaeger_ai.agent.skill_registry import skill_loader

    monkeypatch.setattr(skill_loader, "last_skip_reason", lambda *names: None)
    reason = persona_lane._app_control_unavailable_reason()
    assert reason  # some non-empty fallback string, not a crash/blank


# ── (c) email is registry-derived ─────────────────────────────────


def test_email_group_appears_once_send_email_is_registered(monkeypatch):
    monkeypatch.setattr(persona_lane, "_live_tool_names", lambda: {"send_email"})
    monkeypatch.setattr(persona_lane, "_installed_slots", lambda: set())
    monkeypatch.setattr(persona_lane, "_installed_messaging_channels", lambda: [])
    block = persona_lane.build_self_model_block()
    assert "email" in block


def test_email_group_absent_when_send_email_is_not_registered(monkeypatch):
    monkeypatch.setattr(persona_lane, "_live_tool_names", lambda: {"get_time"})
    monkeypatch.setattr(persona_lane, "_installed_slots", lambda: set())
    monkeypatch.setattr(persona_lane, "_installed_messaging_channels", lambda: [])
    block = persona_lane.build_self_model_block()
    assert "- email" not in block


def test_send_email_actually_registers_the_email_group_on_the_real_registry():
    """Not just the toolset-scoping wiring in isolation — importing the
    real tools/email.py module (as main.py's boot path does) must make
    the live self-model block show the email group."""
    import jaeger_ai.agent.tools.email  # noqa: F401 — registers send_email

    block = persona_lane.build_self_model_block()
    assert "email" in block


# ── cache invalidation ─────────────────────────────────────────────


def test_cache_invalidates_when_a_credential_is_saved():
    layout = _fresh_instance()
    tools.bind(layout)
    try:
        persona_lane.self_model_block()  # populate the cache
        assert persona_lane._self_model_cache  # sanity: something cached

        creds_tool._t_set_credential(name="SOME_TOKEN", value="abc123")

        assert not persona_lane._self_model_cache, (
            "saving a credential must invalidate the self-model cache"
        )
    finally:
        tools.bind(_fresh_instance())


def test_cache_invalidates_when_autostart_is_persisted(monkeypatch):
    layout = _fresh_instance()

    saved_client = m._pipeline.get("client")
    saved_layout = m._pipeline.get("layout")
    saved_config = m._pipeline.get("config")
    from jaeger_ai.core.instance.schemas import load_yaml
    cfg = load_yaml(layout.config_path, Config)
    m._pipeline["client"] = object()
    m._pipeline["layout"] = layout
    m._pipeline["config"] = cfg

    def _fake_start_bridge(name, *, layout, handler, llm_lock=None, bus=None):
        return {"started": True, "channel": name}

    monkeypatch.setattr("jaeger_ai.plugins.start_bridge", _fake_start_bridge)

    try:
        persona_lane.self_model_block()  # populate the cache
        assert persona_lane._self_model_cache

        result = m.activate_plugin_inprocess("telegram")
        assert result["started"] is True

        assert not persona_lane._self_model_cache, (
            "persisting autostart must invalidate the self-model cache"
        )
    finally:
        m._pipeline["client"] = saved_client
        m._pipeline["layout"] = saved_layout
        m._pipeline["config"] = saved_config
