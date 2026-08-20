"""Cron delivery sidecar — channel + recipient per schedule."""

from __future__ import annotations

import types

import pytest

from jaeger_ai.core.runtime import cron_delivery as cd


def _layout(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    return types.SimpleNamespace(root=tmp_path, memory_dir=mem)


def test_remember_and_lookup(tmp_path):
    layout = _layout(tmp_path)
    cd.remember(layout, "morning", channel="telegram", recipient="123")
    assert cd.lookup(layout, "morning") == {
        "channel": "telegram", "recipient": "123",
    }


def test_rejects_unknown_channel(tmp_path):
    with pytest.raises(ValueError):
        cd.remember(_layout(tmp_path), "x", channel="slack", recipient="1")


def test_forget(tmp_path):
    layout = _layout(tmp_path)
    cd.remember(layout, "x", channel="discord", recipient="9")
    assert cd.forget(layout, "x") is True
    assert cd.lookup(layout, "x") is None
