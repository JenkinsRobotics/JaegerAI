"""Standing heartbeat — wake, stay silent, persist the last beat."""

from __future__ import annotations

import types
from datetime import datetime

from jaeger_ai.core.runtime import heartbeat as hb


def _layout(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    return types.SimpleNamespace(root=tmp_path, memory_dir=mem)


def test_seed_writes_the_default_once(tmp_path):
    layout = _layout(tmp_path)
    path = hb.seed_checklist(layout)
    assert path is not None and path.is_file()
    assert "HEARTBEAT_OK" in path.read_text(encoding="utf-8")
    path.write_text("custom\n", encoding="utf-8")
    hb.seed_checklist(layout)
    assert path.read_text(encoding="utf-8") == "custom\n"


def test_silent_ok_accepts_the_exact_token():
    assert hb.is_silent_ok("HEARTBEAT_OK")
    assert hb.is_silent_ok(" heartbeat_ok \n")
    assert hb.is_silent_ok("[SILENT]")
    assert hb.is_silent_ok("")
    assert not hb.is_silent_ok("the board has a new card")


def test_interval_zero_never_fires(tmp_path):
    layout = _layout(tmp_path)
    assert hb.is_due(layout, interval_minutes=0) is False
    assert hb.is_due(layout, interval_minutes=30, enabled=False) is False


def test_first_due_check_starts_the_wait_instead_of_firing(tmp_path):
    layout = _layout(tmp_path)
    now = 1_000_000.0
    assert hb.is_due(layout, interval_minutes=30, now=now) is False
    assert hb.last_beat_at(layout) == now
    assert hb.is_due(layout, interval_minutes=30, now=now + 60) is False
    assert hb.is_due(layout, interval_minutes=30, now=now + 30 * 60) is True


def test_mark_beat_persists_across_a_fresh_layout(tmp_path):
    layout = _layout(tmp_path)
    hb.mark_beat(layout, now=50.0, silent=True)
    other = _layout(tmp_path)
    assert hb.last_beat_at(other) == 50.0


def test_status_names_the_silent_token(tmp_path):
    layout = _layout(tmp_path)
    hb.seed_checklist(layout)
    row = hb.status(layout, interval_minutes=30, enabled=True)
    assert row["enabled"] is True
    assert row["interval_minutes"] == 30
    assert row["checklist_present"] is True
    assert row["silent_ok"] == "HEARTBEAT_OK"


def test_build_prompt_inlines_the_checklist_and_ok_contract(tmp_path):
    layout = _layout(tmp_path)
    # Noon is outside both briefing windows — standing checklist path.
    prompt = hb.build_prompt(layout, now=datetime(2026, 8, 21, 12, 0, 0))
    assert "HEARTBEAT_OK" in prompt
    assert "CHECKLIST:" in prompt
    assert "Heartbeat" in prompt
    assert "briefing — morning" not in prompt


def test_briefing_kind_windows():
    assert hb.briefing_kind(now=datetime(2026, 8, 21, 8, 0, 0)) == "morning"
    assert hb.briefing_kind(now=datetime(2026, 8, 21, 6, 0, 0)) == "morning"
    assert hb.briefing_kind(now=datetime(2026, 8, 21, 10, 59, 0)) == "morning"
    assert hb.briefing_kind(now=datetime(2026, 8, 21, 18, 0, 0)) == "eod"
    assert hb.briefing_kind(now=datetime(2026, 8, 21, 12, 0, 0)) is None
    assert hb.briefing_kind(now=datetime(2026, 8, 21, 22, 0, 0)) is None


def test_morning_build_prompt_is_a_briefing_until_delivered(tmp_path):
    layout = _layout(tmp_path)
    morning = datetime(2026, 8, 21, 8, 30, 0)
    prompt = hb.build_prompt(layout, now=morning)
    assert "briefing — morning" in prompt
    assert "CHECKLIST:" in prompt
    assert "HEARTBEAT_OK" in prompt
    assert not hb.already_briefed(layout, "morning", now=morning)

    hb.mark_beat(layout, now=morning.timestamp(), silent=True)
    assert not hb.already_briefed(layout, "morning", now=morning)

    hb.build_prompt(layout, now=morning)
    hb.mark_beat(layout, now=morning.timestamp() + 1, silent=False)
    assert hb.already_briefed(layout, "morning", now=morning)
    again = hb.build_prompt(layout, now=morning)
    assert "briefing — morning" not in again


def test_eod_briefing_is_independent_of_morning(tmp_path):
    layout = _layout(tmp_path)
    morning = datetime(2026, 8, 21, 8, 0, 0)
    hb.build_prompt(layout, now=morning)
    hb.mark_beat(layout, now=morning.timestamp(), silent=False)
    evening = datetime(2026, 8, 21, 18, 0, 0)
    assert not hb.already_briefed(layout, "eod", now=evening)
    prompt = hb.build_prompt(layout, now=evening)
    assert "briefing — end of day" in prompt


def test_default_checklist_mentions_briefing_windows():
    assert "Morning" in hb.DEFAULT_CHECKLIST
    assert "17–21" in hb.DEFAULT_CHECKLIST
