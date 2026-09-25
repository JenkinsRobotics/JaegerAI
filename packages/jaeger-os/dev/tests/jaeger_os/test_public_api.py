"""The flat public API — what an app imports.

`from jaeger_os import InProcBus, topics` instead of knowing that a Bus
lives in `transport` and Node lives in `nodes.base`. Five subpackages
is a lot to learn before your first line.

The rule these tests defend: these are the SAME objects re-exported,
never a second API wrapping the first. Two ways to do everything is
how a framework grows a beginner dialect that cannot read its own
internals.
"""

from __future__ import annotations

import pytest

import jaeger_os


def test_an_app_can_be_written_from_one_import():
    from jaeger_os import Bus, InProcBus, JaegerApp, Node, topics
    assert all(x is not None for x in (Bus, InProcBus, JaegerApp, Node, topics))


@pytest.mark.parametrize("name,module,attr", [
    ("Bus", "jaeger_os.transport", "Bus"),
    ("InProcBus", "jaeger_os.transport", "InProcBus"),
    ("Node", "jaeger_os.nodes.base", "Node"),
    ("JaegerApp", "jaeger_os.app", "JaegerApp"),
    ("topics", "jaeger_os.contract", "topics"),
    ("discover_modules", "jaeger_os.core.modules", "discover_modules"),
])
def test_re_exports_are_the_same_object(name, module, attr):
    """Not a copy, not a wrapper. If these ever diverge there are two
    APIs and a bug fixed in one is not fixed in the other."""
    import importlib
    assert getattr(jaeger_os, name) is getattr(
        importlib.import_module(module), attr)


def test_topics_resolves_to_the_contract_not_the_shim():
    """`jaeger_os.transport.topics` is a re-export shim that snapshots
    attributes at import time; its own docstring says it is not the
    source of truth. The short path must point at the real one."""
    from jaeger_os.contract import topics as canonical
    assert jaeger_os.topics is canonical


def test_a_wrong_name_lists_the_right_ones():
    """A beginner's most common error is a misspelling. The message
    should answer the question rather than just refuse."""
    with pytest.raises(AttributeError) as exc:
        jaeger_os.InprocBus          # noqa: B018 — wrong capitalisation
    assert "InProcBus" in str(exc.value)


def test_importing_jaeger_os_does_not_drag_in_zmq():
    """`import jaeger_os` must stay cheap. Eager re-exports would pull
    pyzmq, and every CLI that only wanted a version string would pay
    for it."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, jaeger_os; print('zmq' in sys.modules)"],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_the_public_surface_is_small():
    """Every name here is one more thing to learn. Growth should be a
    decision, not a drift."""
    assert len(jaeger_os.__all__) <= 20, (
        f"public API grew to {len(jaeger_os.__all__)} names: "
        f"{sorted(jaeger_os.__all__)}")


def test_dir_shows_what_is_available():
    """Tab-completion in a REPL is how a beginner discovers an API."""
    listed = dir(jaeger_os)
    for name in ("InProcBus", "Node", "topics", "JaegerApp"):
        assert name in listed
