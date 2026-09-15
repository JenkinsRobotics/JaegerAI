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

def test_the_four_frameworks_are_present_and_unique() -> None:
    runtimes = [f.runtime for f in fw.FRAMEWORKS]
    assert sorted(runtimes) == ["hermes", "jaeger", "openclaw", "roundtable"]
    for field in ("runtime", "profile", "display_name", "agent_id"):
        values = [getattr(f, field) for f in fw.FRAMEWORKS]
        assert len(set(values)) == len(values), f"duplicate {field}: {values}"


def test_hermes_profile_is_default() -> None:
    """The trap this module exists for: Hermes' runtime and profile differ.

    Code that treats the two words as interchangeable works for the other
    three frameworks and silently misroutes this one.
    """
    assert fw.framework("hermes").profile == "default"
    assert fw.canonical_runtime("default") == "hermes"
    assert fw.profile_name("hermes") == "default"


@pytest.mark.parametrize(
    ("spelling", "runtime"),
    [
        ("hermes", "hermes"), ("default", "hermes"), ("tp:hermes", "hermes"),
        ("jaeger", "jaeger"), ("native:jaeger", "jaeger"), ("jaegerai", "jaeger"),
        ("openclaw", "openclaw"), ("tp:openclaw", "openclaw"),
        ("roundtable", "roundtable"), ("tp:roundtable", "roundtable"),
        ("  OpenClaw  ", "openclaw"),   # values arrive from HTTP bodies/cookies
    ],
)
def test_every_spelling_resolves(spelling: str, runtime: str) -> None:
    assert fw.canonical_runtime(spelling) == runtime


def test_an_unknown_name_names_the_valid_ones() -> None:
    """A bad profile should tell you what you could have said."""
    with pytest.raises(fw.UnknownFramework) as caught:
        fw.canonical_runtime("gpt5")
    message = str(caught.value)
    assert "gpt5" in message and "openclaw" in message and "default" in message
    assert not fw.is_known("gpt5")


def test_roundtable_composes_the_other_three() -> None:
    assert set(fw.DEBATE_MEMBERS) == {"jaeger", "hermes", "openclaw"}
    assert "roundtable" not in fw.DEBATE_MEMBERS, "a debate cannot debate itself"
    assert set(fw.SOLO_RUNTIMES) == set(fw.DEBATE_MEMBERS)
    for member in fw.DEBATE_MEMBERS:
        assert fw.framework(member).composes == (), f"{member} must answer alone"


def test_every_native_backend_registers_turn_and_reconciler() -> None:
    for runtime in fw.SOLO_RUNTIMES:
        protocol = fw.backend_protocol(runtime)
        assert callable(protocol.turn)
        assert callable(protocol.reconciler)
    with pytest.raises(RuntimeError, match="no complete native backend protocol"):
        fw.backend_protocol("roundtable")


def test_agent_ids_use_a_known_origin_prefix() -> None:
    """``native:`` is Jaeger's own agent, ``tp:`` a third party. The agent
    registry writes these ids; a new prefix means the roster stops matching."""
    for f in fw.FRAMEWORKS:
        assert f.agent_id.split(":", 1)[0] in {"native", "tp"}, f.agent_id


# ── every former copy still agrees ───────────────────────────────────────

def test_webui_profile_list_matches_the_contract() -> None:
    from jaeger_ai.features.webui.adapter.profile_catalog import PROFILES
    assert PROFILES == tuple(
        (f.profile, f.runtime, f.display_name) for f in fw.FRAMEWORKS
    )


def test_webui_normaliser_matches_the_contract() -> None:
    from jaeger_ai.features.webui.adapter.profile_runner import canonical_profile
    for f in fw.FRAMEWORKS:
        assert canonical_profile(f.profile) == f.runtime
        assert canonical_profile(f.runtime) == f.runtime
    assert canonical_profile(None) == "jaeger", "empty profile defaults to Jaeger"
    with pytest.raises(ValueError):
        canonical_profile("not-a-framework")


def test_roundtable_members_match_the_contract() -> None:
    from jaeger_ai.features.roundtable.policy import MEMBERS
    assert tuple(MEMBERS) == fw.DEBATE_MEMBERS


def test_workspace_identities_match_the_contract() -> None:
    from jaeger_ai.core.frameworks.setup import WORKSPACE_IDENTITIES
    assert set(WORKSPACE_IDENTITIES) == set(fw.SOLO_RUNTIMES)


def test_managed_container_names_match_the_contract() -> None:
    from jaeger_ai.core.runtime.agent_workspaces import MANAGED_CONTAINERS
    assert MANAGED_CONTAINERS == {
        f.runtime: f.container for f in fw.FRAMEWORKS if f.container
    }


def test_profile_payload_carries_agent_id() -> None:
    from jaeger_ai.features.webui.adapter.profile_catalog import ProfileCatalog
    rows = ProfileCatalog(lambda _name: True).list()
    assert {r["agent_id"] for r in rows} == {f.agent_id for f in fw.FRAMEWORKS}


def test_a_debate_is_unavailable_when_a_member_is_down() -> None:
    """Readiness cascade, derived rather than hardcoded to 'roundtable'."""
    from jaeger_ai.features.webui.adapter.profile_catalog import ProfileCatalog
    rows = {r["runtime"]: r for r in
            ProfileCatalog(lambda name: name != "openclaw").list()}
    assert rows["openclaw"]["runtime_status"] == "Unavailable"
    assert rows["roundtable"]["runtime_status"] == "Unavailable: OpenClaw"
    assert rows["jaeger"]["runtime_status"] == "Ready"


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


def test_roundtables_jaeger_seat_is_pinned_to_the_jaeger_instance() -> None:
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
