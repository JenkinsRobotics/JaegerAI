"""The framework table is the only copy — proven, not asserted in a docstring.

``jaeger_ai/contract/frameworks.py`` exists because the same mapping used to be
re-derived in eight places, and on 2026-09-14 two of those copies disagreed and
routed a conversation to the wrong backend. A contract that nothing checks
becomes the ninth copy, so these tests do two jobs:

* pin the table itself (the values a wire format and a UI depend on), and
* prove every former copy still agrees with it.
"""
from __future__ import annotations

import pytest

from jaeger_ai.contract import frameworks as fw


# ── the table ────────────────────────────────────────────────────────────

def test_jaeger_is_the_only_framework() -> None:
    """Hermes, OpenClaw and Roundtable were retired on 2026-11-11."""
    assert [f.runtime for f in fw.FRAMEWORKS] == ["jaeger"]
    assert fw.DEBATE_MEMBERS == ()
    for retired in ("hermes", "default", "openclaw", "roundtable", "tp:hermes"):
        assert not fw.is_known(retired), retired


@pytest.mark.parametrize(
    ("spelling", "runtime"),
    [("jaeger", "jaeger"), ("native:jaeger", "jaeger"), ("jaegerai", "jaeger"),
     ("  Jaeger  ", "jaeger")],   # values arrive from HTTP bodies/cookies
)
def test_every_spelling_resolves(spelling: str, runtime: str) -> None:
    assert fw.canonical_runtime(spelling) == runtime


def test_an_unknown_name_names_the_valid_ones() -> None:
    """A bad profile should tell you what you could have said."""
    with pytest.raises(fw.UnknownFramework) as caught:
        fw.canonical_runtime("gpt5")
    message = str(caught.value)
    assert "gpt5" in message and "jaeger" in message
    assert not fw.is_known("gpt5")


def test_every_native_backend_registers_turn_and_reconciler() -> None:
    for runtime in fw.SOLO_RUNTIMES:
        protocol = fw.backend_protocol(runtime)
        assert callable(protocol.turn)
        assert callable(protocol.reconciler)


def test_agent_ids_use_a_known_origin_prefix() -> None:
    """``native:`` is Jaeger's own agent, ``tp:`` a third party. The agent
    registry writes these ids; a new prefix means the roster stops matching."""
    for f in fw.FRAMEWORKS:
        assert f.agent_id.split(":", 1)[0] in {"native", "tp"}, f.agent_id


# ── every former copy still agrees ───────────────────────────────────────







def test_incomplete_backend_registration_is_rejected() -> None:
    with pytest.raises(ValueError, match="turn and reconciler together"):
        fw.Framework(
            runtime="broken",
            profile="broken",
            display_name="Broken",
            agent_id="native:broken",
            turn="example:turn",
        )


def test_chat_endpoint_defaults_are_defined_once_and_use_loopback(monkeypatch) -> None:
    from jaeger_ai.contract import ports

    assert ports.MCP_GATEWAY_URL == f"http://{ports.LOOPBACK}:{ports.MCP_GATEWAY_PORT}/mcp"
    assert ports.OLLAMA_URL == f"http://{ports.LOOPBACK}:{ports.OLLAMA_PORT}"
    assert ports.OLLAMA_OPENAI_URL == ports.OLLAMA_URL + "/v1"


def test_jaeger_turn_is_pinned_to_the_jaeger_instance() -> None:
    """Roundtable's Jaeger member must not follow the UI's active delegate.

    ``~/.jaeger/active_instance`` records which delegate a person last selected;
    selecting "Everyday" rewrites it. ``jaeger_turn`` used a bare
    ``BridgeClient()``, which reads that pointer, so Roundtable sent its Jaeger
    seat to ``instances/everyday/run/bridge.sock`` — no listener, member failed
    with no error recorded, and the whole debate aborted with "a member outcome
    is unknown". Every other member still worked, which made it look like
    Roundtable itself was broken.
    """
    import ast
    import inspect
    import textwrap

    from jaeger_ai.core.frameworks import native_runs

    # Executable lines only — the fix's own docstring names the bad pattern in
    # order to explain it, and a plain substring check matched the prose.
    tree = ast.parse(textwrap.dedent(inspect.getsource(native_runs.jaeger_turn)))
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]          # drop the docstring
    source = ast.unparse(fn)
    assert "BridgeClient()" not in source, (
        "jaeger_turn constructs BridgeClient with no instance again. That "
        "follows ~/.jaeger/active_instance, which a UI delegate switch "
        "rewrites — use jaeger_bridge() instead."
    )
    assert "jaeger_bridge()" in source, (
        "jaeger_turn must reach Jaeger through the pinned helper so the "
        "instance cannot drift with the UI's selected delegate"
    )
