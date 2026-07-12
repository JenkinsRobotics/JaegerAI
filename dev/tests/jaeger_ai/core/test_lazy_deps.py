"""Lazy dependency loading (audit gap #3).

Optional backends (Kokoro TTS, the vision model, the image generator,
the ddgs search client) are not hard dependencies. ``ensure(feature)``
turns a missing backend into a clean, actionable ``FeatureUnavailable``
instead of a raw ImportError — and, only when explicitly enabled,
auto-installs it.
"""

from __future__ import annotations

import pytest

from jaeger_ai.core.models import lazy_deps
from jaeger_ai.core.models.lazy_deps import (
    FeatureUnavailable,
    LAZY_DEPS,
    available,
    ensure,
)


def test_registry_specs_are_well_formed() -> None:
    for fid, spec in LAZY_DEPS.items():
        assert spec.feature == fid
        assert spec.probe and spec.pip and spec.summary


def test_available_returns_a_bool() -> None:
    assert isinstance(available("search.ddgs"), bool)


def test_unknown_feature_is_not_gated() -> None:
    assert available("totally.unknown") is True
    ensure("totally.unknown")   # must not raise


def test_importable_detects_present_and_missing() -> None:
    assert lazy_deps._importable("json") is True
    assert lazy_deps._importable("no_such_module_xyz123") is False


def test_feature_unavailable_carries_remediation() -> None:
    exc = FeatureUnavailable(LAZY_DEPS["search.ddgs"])
    assert "pip install" in exc.remediation
    assert "ddgs" in exc.remediation
    assert "allow_lazy_installs" in exc.remediation


def test_ensure_raises_for_a_missing_backend(monkeypatch) -> None:
    # A feature whose probe module cannot exist — ensure must raise
    # FeatureUnavailable (auto-install is off by default).
    fake = lazy_deps.FeatureSpec(
        "test.fake", "no_such_mod_xyz123", ("fake-pkg",), "fake backend")
    monkeypatch.setitem(LAZY_DEPS, "test.fake", fake)
    with pytest.raises(FeatureUnavailable):
        ensure("test.fake")


def test_ensure_is_a_noop_for_an_importable_backend(monkeypatch) -> None:
    # Probe a module that is always present → ensure does nothing.
    ok = lazy_deps.FeatureSpec("test.ok", "json", ("x",), "always there")
    monkeypatch.setitem(LAZY_DEPS, "test.ok", ok)
    ensure("test.ok")   # must not raise
    assert available("test.ok") is True
