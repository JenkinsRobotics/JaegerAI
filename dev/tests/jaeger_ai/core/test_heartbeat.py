"""Standing heartbeat — wake, stay silent, persist the last beat."""

from __future__ import annotations

import types

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
    prompt = hb.build_prompt(layout)
    assert "HEARTBEAT_OK" in prompt
    assert "CHECKLIST:" in prompt
    assert "Heartbeat" in prompt
