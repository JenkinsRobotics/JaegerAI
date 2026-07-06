"""Group 4 + 5 polish items — POLISH-2/-4/-5 + VOICE-3/-4.

Each block targets one roadmap item so a failure points at the
specific symptom. The wizard items (VOICE-1/-2) have their own
tests under ``test_setup_wizard.py``; POLISH-1 (banner string) is a
1-line constant change and is covered by the existing tui rendering
tests.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[4]


# ── POLISH-2: boot panel respects JAEGER_TOOLSET_SCOPING ────────────


def test_visible_tool_groups_returns_full_set_when_scoping_off(monkeypatch):
    """With ``JAEGER_TOOLSET_SCOPING`` unset/0, the panel renders the
    full categorised catalog — same shape as 0.1.0."""
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)

    from jaeger_os.interfaces.tui.status import (
        TOOL_GROUPS, _visible_tool_groups,
    )
    groups, visible, total = _visible_tool_groups()
    assert groups == TOOL_GROUPS
    assert visible == total
    assert visible == sum(len(v) for v in TOOL_GROUPS.values())


def test_visible_tool_groups_filters_to_CORE_when_scoping_on(monkeypatch):
    """With scoping on, the panel shows only the CORE intersection
    so the displayed tools match what the model actually sees."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)

    from jaeger_os.interfaces.tui.status import _visible_tool_groups
    from jaeger_os.agent.skill_registry.toolset_scoping import CORE
    groups, visible, total = _visible_tool_groups()

    # Every displayed tool is in CORE (the model-visible set).
    flat = [t for tools in groups.values() for t in tools]
    assert all(t in CORE for t in flat), (
        f"non-CORE tool leaked into the lean-surface panel: "
        f"{[t for t in flat if t not in CORE]}"
    )
    # And visible_count < total — the whole point of POLISH-2.
    assert visible < total


# ── VOICE-3: wake-word at FIRST 2 tokens only ───────────────────────


def test_wake_phrase_matches_at_head():
    from jaeger_os.plugins.whisper_stt._base import _find_wake_in_text
    matched, remainder = _find_wake_in_text(
        "hey jaeger what is the weather",
        ("hey jaeger",),
        wake_match_threshold=0.78,
    )
    assert matched is True
    assert remainder == "what is the weather"


def test_wake_phrase_inside_sentence_is_ignored():
    """Pre-VOICE-3, "yes I think hey jaeger is cool" wrongly
    triggered. After VOICE-3 the wake word MUST be the opening
    of the sentence."""
    from jaeger_os.plugins.whisper_stt._base import _find_wake_in_text
    matched, remainder = _find_wake_in_text(
        "yes I think hey jaeger is cool",
        ("hey jaeger",),
        wake_match_threshold=0.78,
    )
    assert matched is False
    assert remainder == ""


def test_wake_phrase_fuzzy_head_match_still_works():
    """Whisper sometimes mishears 'jaeger' as 'yeager' / 'jager'.
    The fuzzy fallback should still accept the head window even
    when it's not an exact match."""
    from jaeger_os.plugins.whisper_stt._base import _find_wake_in_text
    matched, remainder = _find_wake_in_text(
        "hey yeager pick up the trash",
        ("hey jaeger",),
        wake_match_threshold=0.7,
    )
    assert matched is True
    # The remainder should be everything after the matched head.
    assert "pick up the trash" in remainder


def test_continuous_extract_command_head_only(monkeypatch):
    """The continuous-mode wake matcher (``_extract_command``)
    enforces the same head-only contract."""
    from jaeger_os.plugins.whisper_stt.continuous import (
        WhisperSTTContinuous,
    )
    # Hand-build a stub instance with just the attrs _extract_command
    # uses — saves wiring a full mic stream for a logic test.
    stub = WhisperSTTContinuous.__new__(WhisperSTTContinuous)
    stub.wake_phrases = ("hey jaeger",)
    stub.wake_match_threshold = 0.78
    assert stub._extract_command("hey jaeger turn on the lights") == "turn on the lights"
    assert stub._extract_command("turn the lights on hey jaeger") is None


# ── VOICE-4: pre-wake transcripts surface visibly ───────────────────


def test_pre_wake_transcript_is_logged_as_not_sent(capsys, monkeypatch):
    """When wake-required mode is on AND no wake match, the
    transcript should print as ``[mic heard X — not sent]`` AND not
    land in the committed queue."""
    from jaeger_os.plugins.whisper_stt.continuous import WhisperSTTContinuous
    stub = WhisperSTTContinuous.__new__(WhisperSTTContinuous)
    stub.require_wake_word = True
    stub.wake_phrases = ("hey jaeger",)
    stub.wake_match_threshold = 0.78
    stub._state = "WAKE"
    stub._followup_deadline = 0.0
    import queue as _queue
    stub._committed_q = _queue.Queue()

    # 2026-06-07: stt_verbose() gates the "not sent" stdout print
    # since the TUI's voice-activity log replaced inline debug output
    # for the common case.  This test still verifies the BEHAVIOUR
    # (phrase not committed) and asserts the verbose-mode log path
    # still works when JAEGER_STT_VERBOSE=1.
    import os
    os.environ["JAEGER_STT_VERBOSE"] = "1"
    try:
        stub._commit("ambient podcast audio about nothing")
        out = capsys.readouterr().out
        assert "not sent" in out
        assert "ambient podcast audio about nothing" in out
    finally:
        os.environ.pop("JAEGER_STT_VERBOSE", None)
    # Nothing was queued — the load-bearing behavioural assertion.
    assert stub._committed_q.empty()


def test_wake_match_is_committed(capsys):
    """Positive control — when the wake phrase IS at the head, the
    committed queue gets the command tail."""
    from jaeger_os.plugins.whisper_stt.continuous import WhisperSTTContinuous
    stub = WhisperSTTContinuous.__new__(WhisperSTTContinuous)
    stub.require_wake_word = True
    stub.wake_phrases = ("hey jaeger",)
    stub.wake_match_threshold = 0.78
    stub._state = "WAKE"
    stub._followup_deadline = 0.0
    import queue as _queue
    stub._committed_q = _queue.Queue()

    stub._commit("hey jaeger what time is it")
    assert stub._committed_q.qsize() == 1
    assert "what time is it" in stub._committed_q.get_nowait()


# ── POLISH-4: requires_toolsets auto-load on skill(view) ────────────


def test_skill_view_auto_loads_required_toolsets(monkeypatch, tmp_path):
    """When a viewed skill declares ``requires_toolsets``, the
    dispatcher auto-loads them and reports the result. Saves a
    round-trip ``load_tools`` call."""
    from jaeger_os.agent.tools import skills as skills_tools
    from jaeger_os.agent.skill_registry import playbook_skills as _pb

    # Make a real on-disk skill file so the dispatcher's
    # ``s.path.read_text`` succeeds.
    skill_md = tmp_path / "test_skill.md"
    skill_md.write_text("# test skill\n\nSome content.", encoding="utf-8")

    class _FakeSkill:
        name = "test_skill"
        category = "test"
        origin = "test"
        description = "fake test skill"
        tags = ()
        path = skill_md
        platforms = ()
        requires_tools = ()
        requires_toolsets = ["files", "code"]

    monkeypatch.setattr(
        _pb, "find_playbook",
        lambda name: _FakeSkill() if name == "test_skill" else None,
        raising=True,
    )

    loaded: list[str] = []

    def fake_enable(name: str) -> bool:
        loaded.append(name)
        return True

    from jaeger_os.agent.skill_registry import toolset_scoping as _ts
    monkeypatch.setattr(_ts, "enable_toolset", fake_enable, raising=True)
    monkeypatch.setattr(_ts, "active_toolset_names",
                        lambda: {"files", "code"}, raising=True)

    result = skills_tools.skill(action="view", name="test_skill")
    assert result.get("ok") is True, result
    # Both toolsets the skill required were auto-enabled.
    assert sorted(loaded) == ["code", "files"]
    assert sorted(result.get("auto_loaded_toolsets", [])) == ["code", "files"]


# ── POLISH-5: agent_contract.md generator ───────────────────────────


def test_agent_contract_script_writes_and_check_passes():
    """End-to-end: run the generator, then run ``--check`` — clean."""
    script = REPO / "dev" / "scripts" / "generate_agent_contract.py"
    doc = REPO / "jaeger_os" / "docs" / "agent_contract.md"
    # Write.
    r = subprocess.run([sys.executable, str(script)],
                       capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, r.stderr
    assert doc.exists()
    # Check — must report up to date.
    r2 = subprocess.run([sys.executable, str(script), "--check"],
                        capture_output=True, text=True, timeout=15)
    assert r2.returncode == 0, r2.stderr
    assert "up to date" in r2.stdout


def test_agent_contract_check_detects_staleness(tmp_path, monkeypatch):
    """If the doc on disk doesn't match the rendered output,
    ``--check`` should exit 1 and say so."""
    script = REPO / "dev" / "scripts" / "generate_agent_contract.py"
    doc = REPO / "jaeger_os" / "docs" / "agent_contract.md"
    # Stash, scribble, restore.
    original = doc.read_text(encoding="utf-8")
    doc.write_text("stale content\n", encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(script), "--check"],
                           capture_output=True, text=True, timeout=15)
        assert r.returncode == 1
        assert "out of date" in r.stderr
    finally:
        doc.write_text(original, encoding="utf-8")


def test_agent_contract_includes_every_rule_section():
    """The generated doc must mention every rule constant the assemble
    pipeline references — otherwise a new constant landing in rules.py
    would silently miss the doc.

    Post-consolidation, the behavioural rule text (identity, mandatory
    tool rules, operating discipline, tool-usage mechanics, runtime
    tail) moved OUT of rules.py constants and into the externalized
    ``framework_agent.md`` / ``three_laws.md`` documents. The only rule
    constants left in rules.py are the two mutually-exclusive
    toolset-surface notes, so those are the only names the doc must
    still carry."""
    doc = (REPO / "jaeger_os" / "docs" / "agent_contract.md").read_text(encoding="utf-8")
    for name in (
        "RUNTIME_TOOLSET_SCOPED",
        "RUNTIME_TOOLSET_UNSCOPED",
    ):
        assert f"`{name}`" in doc, f"{name} missing from agent_contract.md"
