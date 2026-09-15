"""Session attribution, and the guard that stops prune deleting real history.

Two things are pinned here:

* every id shape a live store actually holds resolves to the right framework
  and surface, and an id that names neither stays ``None`` rather than being
  guessed into a bucket;
* :func:`prune_sessions` never treats "count not recorded" as "count is zero".
  A dry run once offered to delete 64 real Gateway conversations as empty,
  because that store has no message-count column and the reader defaulted the
  missing value to 0.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from jaeger_ai.contract import sessions as cs
from jaeger_ai.contract.frameworks import FRAMEWORKS


# ── id shapes seen in live stores ────────────────────────────────────────

@pytest.mark.parametrize(
    ("session_id", "runtime"),
    [
        ("webui-hermes-25e319419efc8aba3d8423ac69144035", "hermes"),
        ("webui-openclaw-91cc0a21", "openclaw"),
        ("webui-jaeger-4d2c2b3f", "jaeger"),
        # Roundtable joins its per-member legs with ':', not '-'. Matching only
        # '-' left every debate leg unattributed.
        ("roundtable-hermes:44f0050a92ba504e860df5f1768f6e6d", "roundtable"),
        ("focus-jaeger-abc123", "jaeger"),
        # Pre-convention ids genuinely name no framework.
        ("01235f3384e1", None),
        ("20260829_223822_9d624e", None),
        ("dispatcher", None),
        ("", None),
    ],
)
def test_runtime_from_session_id(session_id, runtime) -> None:
    assert cs.runtime_from_session_id(session_id) == runtime


def test_a_roundtable_leg_belongs_to_the_debate_not_the_member() -> None:
    """``roundtable-hermes:…`` is Hermes answering *for* a Roundtable debate."""
    assert cs.runtime_from_session_id("roundtable-hermes:abc") == "roundtable"
    assert cs.runtime_from_session_id("webui-hermes-abc") == "hermes"


def test_minting_and_decoding_round_trip() -> None:
    for framework in FRAMEWORKS:
        minted = cs.native_session_id(framework.profile, "browser-key")
        assert cs.runtime_from_session_id(minted) == framework.runtime


@pytest.mark.parametrize(
    ("source", "surface"),
    [("webui", "webui"), ("cli", "cli"), ("api_server", "api"),
     ("terminal", "cli"), ("TUI", "tui"), ("nonsense", None), (None, None)],
)
def test_surface_normalisation(source, surface) -> None:
    assert cs.normalise_surface(source) == surface


def test_a_surface_can_never_become_a_profile() -> None:
    """Surfaces and frameworks share a namespace in sloppy code; they must not
    overlap, or a row lands under a profile called "telegram"."""
    runtimes = {f.runtime for f in FRAMEWORKS} | {f.profile for f in FRAMEWORKS}
    assert not (cs.SURFACES & runtimes)


# ── attribution precedence ───────────────────────────────────────────────

def test_recorded_profile_beats_the_id() -> None:
    found = cs.attribute("webui-hermes-abc", "webui", profile="openclaw")
    assert found.runtime == "openclaw"


def test_id_beats_the_store_it_was_found_in() -> None:
    found = cs.attribute("webui-openclaw-abc", "webui", store_runtime="hermes")
    assert found.runtime == "openclaw"


def test_store_is_the_last_resort_not_a_guess() -> None:
    """A bare id in Hermes' own database IS a Hermes conversation."""
    assert cs.attribute("01235f3384e1", "cli", store_runtime="hermes").runtime == "hermes"
    assert cs.attribute("01235f3384e1", "cli").runtime is None


def test_a_webui_prefix_states_its_own_surface() -> None:
    """Hermes records these as ``api_server`` because the adapter posted them,
    but the id says a browser started the conversation."""
    assert cs.attribute("webui-hermes-abc", "api_server").surface == "webui"
    assert cs.attribute("webui-hermes-abc", None).surface == "webui"
    # An explicitly-recorded terminal source is never overridden.
    assert cs.attribute("webui-hermes-abc", "cli").surface == "cli"


def test_browser_and_terminal_are_distinguishable() -> None:
    assert cs.attribute("x", "webui").started_in_browser
    assert cs.attribute("x", "cli").started_in_terminal
    assert not cs.attribute("x", "cron").started_in_browser
    assert not cs.attribute("x", "cron").started_in_terminal


# ── prune must not delete what it cannot measure ─────────────────────────

def _store(path, *, with_count: bool) -> None:
    conn = sqlite3.connect(path)
    cols = "id TEXT PRIMARY KEY, title TEXT, source TEXT, started_at REAL"
    if with_count:
        cols += ", message_count INTEGER"
    conn.execute(f"CREATE TABLE sessions ({cols})")
    old = time.time() - 90 * 86400
    rows = [("old-empty", "junk", "webui", old),
            ("old-real", "a real conversation", "webui", old)]
    if with_count:
        conn.executemany("INSERT INTO sessions VALUES (?,?,?,?,?)",
                         [(*rows[0], 0), (*rows[1], 42)])
    else:
        conn.executemany("INSERT INTO sessions VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()


def _endpoint(name, path, *, with_count: bool):
    from jaeger_ai.features.session_search.endpoints import Endpoint
    return Endpoint(name, path, id_col="id", profile_col=None, source_col="source",
                    title_col="title", time_col="started_at",
                    count_col="message_count" if with_count else None)


def test_prune_skips_a_store_with_no_message_count(tmp_path, monkeypatch) -> None:
    """The bug this test exists for: the Gateway store records no message
    count, the reader defaulted it to 0, and a dry run offered to delete 64
    real conversations as "empty"."""
    from jaeger_ai.features.session_search import endpoints as ep

    path = tmp_path / "countless.db"
    _store(path, with_count=False)
    monkeypatch.setattr(ep, "endpoints", lambda: [_endpoint("countless", path, with_count=False)])

    report = ep.prune_sessions(30, dry_run=True)
    assert report["removed"].get("countless", []) == [], (
        "prune offered to delete rows from a store it cannot measure"
    )
    assert "countless" in report["skipped"]


def test_prune_removes_only_the_empty_old_row(tmp_path, monkeypatch) -> None:
    from jaeger_ai.features.session_search import endpoints as ep

    path = tmp_path / "counted.db"
    _store(path, with_count=True)
    monkeypatch.setattr(ep, "endpoints", lambda: [_endpoint("counted", path, with_count=True)])

    assert ep.prune_sessions(30, dry_run=True)["removed"]["counted"] == ["old-empty"]

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2, "dry run wrote"
    conn.close()

    ep.prune_sessions(30, dry_run=False)
    conn = sqlite3.connect(path)
    remaining = [r[0] for r in conn.execute("SELECT id FROM sessions")]
    conn.close()
    assert remaining == ["old-real"]


def test_prune_refuses_a_nonsense_cutoff(tmp_path, monkeypatch) -> None:
    from jaeger_ai.features.session_search import endpoints as ep
    with pytest.raises(ValueError):
        ep.prune_sessions(0)


def test_unknown_count_is_none_not_zero(tmp_path, monkeypatch) -> None:
    from jaeger_ai.features.session_search import endpoints as ep
    path = tmp_path / "countless.db"
    _store(path, with_count=False)
    monkeypatch.setattr(ep, "endpoints", lambda: [_endpoint("countless", path, with_count=False)])
    assert all(r.message_count is None for r in ep.all_sessions())
