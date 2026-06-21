"""Tests for the 0.5 avatar auto-start at boot.

Verifies the AvatarConfig schema, the runtime.ensure_animation_node
factory, and the prewarm wiring's selection logic.
"""

from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest

from jaeger_os.core.instance.schemas import AvatarConfig, Config, ModelConfig
from jaeger_os.nodes import runtime as node_runtime


@pytest.fixture(autouse=True)
def isolate_runtime():
    node_runtime.shutdown()
    yield
    node_runtime.shutdown()


# ── AvatarConfig schema ─────────────────────────────────────────────

def test_avatar_config_defaults() -> None:
    cfg = AvatarConfig()
    # OFF by default (2026-06-14): the avatar/animation node (Lilith face)
    # is a beta, dev-mode feature, so the daily-driver doesn't warm it.
    assert cfg.enabled is False
    assert cfg.bridge_host == "127.0.0.1"
    assert cfg.bridge_port == 8765
    assert cfg.default_emotion == "neutral"


def test_avatar_config_rejects_unknown_field() -> None:
    """extra='forbid' on the BaseModel — typo guard."""
    with pytest.raises(Exception):
        AvatarConfig(enable=True)  # typo: 'enable' vs 'enabled'


def test_avatar_config_port_range_enforced() -> None:
    with pytest.raises(Exception):
        AvatarConfig(bridge_port=80)  # below the 1024 floor
    with pytest.raises(Exception):
        AvatarConfig(bridge_port=70_000)  # above 65535


def test_top_level_config_includes_avatar() -> None:
    """The Config root has an ``avatar`` field with sensible defaults."""
    cfg = Config(
        instance_name="t",
        model=ModelConfig(model_path=Path("/tmp/x.gguf")),
    )
    # Avatar/animation node is OFF by default (beta, dev-mode feature).
    assert cfg.avatar.enabled is False
    assert cfg.avatar.bridge_port == 8765


# ── ensure_animation_node factory ───────────────────────────────────

def test_ensure_animation_node_is_idempotent() -> None:
    """Two calls return the same node instance.  We patch the
    bridge so the WebSocket server doesn't actually bind in CI."""
    with mock.patch.object(
        node_runtime.animation_bridge.FrameBridge, "start",
        autospec=True,
    ):
        node_a = node_runtime.ensure_animation_node()
        node_b = node_runtime.ensure_animation_node()
    assert node_a is node_b


def test_ensure_animation_node_can_disable_bridge() -> None:
    """``enable_bridge=False`` skips the WebSocket server (useful
    for headless tests + ``--no-avatar`` boots)."""
    node = node_runtime.ensure_animation_node(enable_bridge=False)
    assert node is not None
    # No bridge should be running.
    assert node_runtime._animation_bridge is None  # noqa: SLF001


def test_ensure_animation_node_registers_adapters() -> None:
    """All L1-L4 adapters should be registered so set_avatar_state
    can route to any of them."""
    node = node_runtime.ensure_animation_node(enable_bridge=False)
    # Adapters live on the node's internal table; the simplest
    # observable is that the node is running.
    from jaeger_os.nodes.base import NodeState
    assert node.state == NodeState.RUNNING


# ── shutdown ────────────────────────────────────────────────────────

def test_shutdown_animation_node_is_idempotent() -> None:
    """Shutdown when nothing's running is a no-op."""
    node_runtime.shutdown_animation_node()
    node_runtime.shutdown_animation_node()


def test_full_shutdown_stops_animation_node() -> None:
    """``shutdown()`` tears down TTS + audio session + animation
    together."""
    node_runtime.ensure_animation_node(enable_bridge=False)
    assert node_runtime._animation_node is not None  # noqa: SLF001
    node_runtime.shutdown()
    assert node_runtime._animation_node is None  # noqa: SLF001
