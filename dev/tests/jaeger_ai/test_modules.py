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


def test_declared_slots_match_what_discovery_resolves() -> None:
    """The named provider must be the one that actually won its slot."""
    from jaeger_os.contract.modules import ModuleSpec
    from jaeger_os.core.modules import discover_modules

    def walk(x):
        if isinstance(x, ModuleSpec):
            yield x
        elif isinstance(x, dict):
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                yield from walk(v)

    by_slot = {m.slot: m for m in walk(discover_modules())}
    for mod in INTEGRATIONS:
        if not mod.available():
            continue
        spec = by_slot.get(mod.SLOT)
        assert spec is not None, f"nothing filled slot {mod.SLOT!r}"
        # Compare against where the winning module SHIPS FROM, not its
        # manifest ``module`` name: those are deliberately different
        # (import package ``jaeger_kokoro_tts`` ships module
        # ``kokoro_tts``). The claim this file makes is about the
        # package, so that is what gets checked.
        assert mod.PACKAGE in str(spec.source_dir), (
            f"{mod.PACKAGE} claims slot {mod.SLOT!r}, but discovery "
            f"resolved {spec.module!r} from {spec.source_dir}"
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
    from jaeger_agent.node import DEFAULT_RUNTIME_FACTORY

    assert jaeger_agent.RUNTIME_FACTORY != DEFAULT_RUNTIME_FACTORY
    module_name, _, attribute = jaeger_agent.RUNTIME_FACTORY.partition(":")
    import importlib

    assert callable(getattr(importlib.import_module(module_name), attribute))
