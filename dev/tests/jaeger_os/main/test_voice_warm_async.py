"""``warm_plugins_async`` / ``voice_warm_status`` / ``wait_for_voice_warm``
— 0.8.1 field bug #2: "voice warm off the boot critical path".

Boot used to call ``warm_plugins(config)`` synchronously inside
``boot_for_tui`` — the window/bridge only became interactive after
whisper + kokoro (+ vision/avatar/hardware) finished loading, which
could be minutes on a cold cache or a slow network. These tests cover
the background-thread handshake in isolation (``readiness.warm_all``
itself is mocked out — no real audio backend touched).
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os.main import (
    _pipeline,
    voice_warm_status,
    wait_for_voice_warm,
    warm_plugins_async,
)


@pytest.fixture(autouse=True)
def _reset_pipeline_warm_state():
    old_done = _pipeline.get("voice_warm_done")
    old_readiness = _pipeline.get("readiness")
    yield
    _pipeline["voice_warm_done"] = old_done
    _pipeline["readiness"] = old_readiness


def test_voice_warm_status_before_any_warm_started():
    _pipeline.pop("voice_warm_done", None)
    assert voice_warm_status() == "voice: not started"


def test_wait_for_voice_warm_true_when_never_backgrounded():
    _pipeline.pop("voice_warm_done", None)
    assert wait_for_voice_warm(timeout_s=0.01) is True


def test_warm_plugins_async_returns_immediately_and_flips_done(monkeypatch):
    """The core contract: the call returns before the (mocked, slow)
    warm finishes — that's what makes boot non-blocking — and the
    done-event / readiness report flip once the background thread
    actually finishes."""
    release = threading.Event()

    def _slow_warm_all(config):
        release.wait(timeout=5.0)
        return []

    monkeypatch.setattr(
        "jaeger_os.core.runtime.readiness.warm_all", _slow_warm_all,
    )
    monkeypatch.setattr(
        "jaeger_os.core.runtime.readiness.summarize", lambda statuses: "",
    )
    monkeypatch.setattr(
        "jaeger_os.core.runtime.readiness.all_go", lambda statuses: True,
    )

    started = time.monotonic()
    warm_plugins_async(object(), log_timeout_s=5.0)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, "warm_plugins_async must not block on the warm itself"

    assert voice_warm_status() == "voice: warming…"
    assert wait_for_voice_warm(timeout_s=0.05) is False  # still running

    release.set()
    assert wait_for_voice_warm(timeout_s=5.0) is True
    assert voice_warm_status() == "voice: ready"
    assert _pipeline["readiness"]["all_go"] is True


def test_warm_plugins_async_surfaces_a_failed_background_warm(monkeypatch):
    def _raising_warm_all(config):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "jaeger_os.core.runtime.readiness.warm_all", _raising_warm_all,
    )

    warm_plugins_async(object(), log_timeout_s=5.0)
    assert wait_for_voice_warm(timeout_s=5.0) is True
    status = voice_warm_status()
    assert "warm failed" in status
    assert "boom" in status
    # A failed warm thread must still flip the handshake — otherwise
    # every later wait_for_voice_warm() call would block for its full
    # timeout forever instead of returning promptly.
    assert _pipeline["voice_warm_done"].is_set()
