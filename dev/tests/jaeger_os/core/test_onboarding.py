"""First-boot onboarding — permissions posture, provider selection,
and the factory-reset wipe.

The setup wizard itself is interactive (``input()``) and not unit-tested
here; these cover the persistent pieces around it.
"""

from __future__ import annotations

from jaeger_os.core.safety.permissions import AllowAllProvider, ConsoleConfirmationProvider
from jaeger_os.core.instance.schemas import Config, ModelConfig, PermissionsConfig
from jaeger_os.interfaces.tui.slash_commands import _factory_reset_instance
from jaeger_os.main import _confirmation_provider


def _config(mode: str) -> Config:
    return Config(
        instance_name="t",
        model=ModelConfig(model_path="gemma-4-26b-a4b-it-q4_k_m"),
        permissions=PermissionsConfig(mode=mode),
    )


# ── permissions posture ──────────────────────────────────────────────


def test_permissions_default_is_confirm():
    assert PermissionsConfig().mode == "confirm"


def test_confirm_mode_selects_interactive_provider():
    provider = _confirmation_provider(_config("confirm"))
    assert isinstance(provider, ConsoleConfirmationProvider)


def test_allow_mode_selects_auto_approve_provider():
    """'allow' is the persisted posture for a trusted unattended robot —
    it must resolve to the auto-approve provider, so nothing prompts."""
    provider = _confirmation_provider(_config("allow"))
    assert isinstance(provider, AllowAllProvider)


# ── factory reset ────────────────────────────────────────────────────


def test_factory_reset_wipes_instance_to_first_boot(tmp_path):
    root = tmp_path / "inst"
    (root / "skills" / "weather_v1").mkdir(parents=True)
    (root / "memory").mkdir()
    (root / "logs").mkdir()
    # config trio + agent-accumulated state
    (root / "config.yaml").write_text("instance_name: t\n")
    (root / "identity.yaml").write_text("name: T\n")
    (root / "manifest.json").write_text("{}")
    (root / "skills" / ".gitkeep").write_text("")
    (root / "skills" / "weather_v1" / "SKILL.md").write_text("x")
    (root / "memory" / ".gitkeep").write_text("")
    (root / "memory" / "facts.json").write_text("{}")
    (root / "logs" / ".gitkeep").write_text("")
    (root / "logs" / "audit.log").write_text("...")

    _factory_reset_instance(root)

    # the config trio is gone → next boot sees no instance → wizard runs
    assert not (root / "config.yaml").exists()
    assert not (root / "identity.yaml").exists()
    assert not (root / "manifest.json").exists()
    # agent-accumulated state is cleared
    assert not (root / "skills" / "weather_v1").exists()
    assert not (root / "memory" / "facts.json").exists()
    assert not (root / "logs" / "audit.log").exists()
    # the empty skeleton (.gitkeep) survives so the dirs persist
    assert (root / "skills" / ".gitkeep").exists()
    assert (root / "memory" / ".gitkeep").exists()
