"""jaeger_ai/modules/ — the named integrations for imported modules.

The directory's whole value is that it stays honest: a file per imported
module, named for the real package, declaring the slot it fills. These
checks fail if a file drifts from what discovery actually resolves —
which is exactly when an operator reading the directory would be misled.
"""

from __future__ import annotations

import pytest

from jaeger_ai.modules import installed, summary
from jaeger_ai.modules import jaeger_agent, jaeger_kokoro_tts, jaeger_whisper_stt

INTEGRATIONS = (jaeger_agent, jaeger_kokoro_tts, jaeger_whisper_stt)


@pytest.mark.parametrize("mod", INTEGRATIONS, ids=lambda m: m.PACKAGE)
def test_integration_declares_the_full_surface(mod) -> None:
    assert mod.SLOT and mod.PACKAGE and mod.WATCH
    assert callable(mod.available)
    # The filename must BE the package it integrates — that is the
    # convention's only real rule.
    assert mod.__name__.rsplit(".", 1)[-1] == mod.PACKAGE


def test_slots_are_distinct() -> None:
    """One file per slot; two files claiming `tts` means one is stale."""
    slots = [m.SLOT for m in INTEGRATIONS]
    assert sorted(slots) == sorted(set(slots))


def test_declared_slots_have_the_expected_discovery_provider() -> None:
    """Every named binding must be registered among its slot's providers."""
    from jaeger_os.core.modules import discover_modules

    # Discovery lists ALL providers; entry-point enumeration order does not
    # select a winner. JaegerAI's product binding and the reusable agent can
    # both contribute a mind. The app injects its runtime explicitly below.
    by_slot = discover_modules()
    for mod in INTEGRATIONS:
        if not mod.available():
            continue
        candidates = by_slot.get(mod.SLOT, [])
        assert candidates, f"nothing filled slot {mod.SLOT!r}"
        # The framework contract identifies the provider through its
        # importable factory; ModuleSpec deliberately carries no source-tree
        # path because installed wheels need not retain one.
        discovery_package = getattr(mod, "DISCOVERY_PACKAGE", mod.PACKAGE)
        providers = [spec.factory.split(":", 1)[0] for spec in candidates]
        assert any(
            provider == discovery_package or provider.startswith(discovery_package + ".")
            for provider in providers
        ), (
            f"{mod.PACKAGE} claims slot {mod.SLOT!r}, but discovery "
            f"found no {discovery_package!r} binding among {providers!r}"
        )


def test_installed_gate_does_not_raise_on_nonsense() -> None:
    assert installed("definitely_not_a_real_package_xyz") is False


def test_summary_reports_every_integration() -> None:
    rows = summary()
    assert len(rows) == len(INTEGRATIONS)
    assert {r["slot"] for r in rows} == {m.SLOT for m in INTEGRATIONS}


def test_jaeger_ai_supplies_its_own_runtime_not_the_module_default() -> None:
    """JaegerAI owns instances/memory/personas, so it must NOT ride the
    config-built default runtime — that is the embed path for other apps."""
    from jaeger_agent.core.node import DEFAULT_RUNTIME_FACTORY

    assert jaeger_agent.RUNTIME_FACTORY != DEFAULT_RUNTIME_FACTORY
    module_name, _, attribute = jaeger_agent.RUNTIME_FACTORY.partition(":")
    import importlib

    assert callable(getattr(importlib.import_module(module_name), attribute))
