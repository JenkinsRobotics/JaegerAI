"""Tests for jaeger_ai.features.ops_health honesty helpers."""

from __future__ import annotations

from jaeger_ai.features.ops_health import check_plane_health


def test_plane_ok_when_bridge_ok_and_no_adapters():
    health = check_plane_health(bridge_health=lambda: {"ok": True})
    assert health.ok is True
    assert health.bridge_ok is True
    assert health.as_dict()["honest"] is True


def test_split_brain_adapter_up_bridge_down(monkeypatch):
    monkeypatch.setattr(
        "jaeger_ai.features.ops_health.honesty._http_ok",
        lambda url, timeout_s=2.0: True,
    )
    health = check_plane_health(
        adapter_urls={"jaeger": "http://127.0.0.1:8642/health"},
        bridge_health=lambda: {"ok": False, "error": "not listening"},
    )
    assert health.bridge_ok is False
    assert health.adapters["jaeger"] is True
    assert health.ok is False
    assert health.details.get("split_brain") is True


def test_require_bridge_false_allows_adapter_only(monkeypatch):
    monkeypatch.setattr(
        "jaeger_ai.features.ops_health.honesty._http_ok",
        lambda url, timeout_s=2.0: True,
    )
    health = check_plane_health(
        adapter_urls={"jaeger": "http://127.0.0.1:8642/health"},
        bridge_health=lambda: {"ok": False},
        require_bridge=False,
    )
    # Still fail closed on split-brain when adapters report up.
    assert health.ok is False
