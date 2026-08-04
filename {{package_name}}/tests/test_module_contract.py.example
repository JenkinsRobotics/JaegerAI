"""Module-contract smoke test for {{package_name}}.

Not part of a host project's main test suite by default (mirrors
jaeger_os/nodes/kokoro_tts/tests/test_module_contract.py, which is
excluded from JaegerOS's own testpaths and run directly). Run with:

    pytest src/{{package_name}}/tests
    python -m {{package_name}}.tests.test_module_contract

Three things a module must get right, proven here without touching real
hardware, models, or a running JaegerOS bus:

  1. module.yaml parses and carries the fields module discovery requires.
  2. The factory (module.yaml's `factory:` target) builds a live,
     correctly-wired node on an injected bus.
  3. The node's actual bus contract (command in -> result out) works, via
     a fake engine so no real dependency is invoked.

Copy to test_module_contract.py (drop the .example suffix) once
module.yaml, node.py, and __init__.py are real.
"""

from __future__ import annotations

import pathlib

import yaml

_MODULE_DIR = pathlib.Path(__file__).resolve().parent.parent


def test_module_yaml_validates() -> None:
    doc = yaml.safe_load((_MODULE_DIR / "module.yaml").read_text())
    assert doc["module"]
    assert doc["slot"]
    assert doc["version"]
    assert "consumes" in doc
    assert "produces" in doc
    assert "tools" in doc
    assert doc["factory"]


def test_factory_builds_a_live_node_on_a_fake_bus() -> None:
    """The factory constructs a real node wired to a real (but
    not-yet-warmed) engine — no model load, no hardware I/O, no network."""
    # from {{package_name}} import make_{{package_name}}_node
    #
    # class _FakeBus:
    #     def subscribe(self, *a, **kw): ...
    #     def publish(self, *a, **kw): ...
    #
    # node = make_{{package_name}}_node(_FakeBus(), {})
    # assert node.bus is not None
    # assert node.engine is not None
    pass  # replace with the real assertions above once node.py is real


def test_command_round_trip_with_a_fake_engine() -> None:
    """The node's bus contract, independent of the real factory: publish
    a command, get a result back. The dependency-injection seam
    (Engine Protocol) is what makes this possible without real hardware
    or models — same pattern as kokoro_tts's Synthesizer Protocol."""

    class _FakeEngine:
        def do_the_thing(self, payload):
            return {"ok": True}

        def shutdown(self):
            pass

    # from {{package_name}}.node import {{PackageName}}Node
    #
    # class _FakeBus:
    #     def subscribe(self, *a, **kw): ...
    #     def publish(self, *a, **kw): ...
    #
    # node = {{PackageName}}Node(bus=_FakeBus(), engine=_FakeEngine())
    # node.setup()
    # node._on_command({"payload": "smoke"})
    # node.tick()
    # node.teardown()
    pass  # replace with the real assertions above once node.py is real


if __name__ == "__main__":
    test_module_yaml_validates()
    test_factory_builds_a_live_node_on_a_fake_bus()
    test_command_round_trip_with_a_fake_engine()
    print("{{package_name}} module contract smoke: OK")
