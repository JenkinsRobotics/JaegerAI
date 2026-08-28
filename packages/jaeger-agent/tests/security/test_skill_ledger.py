"""Skill mutation ledger + single-edit rollback.

Ported from hermes-agent ``tools/skill_ledger.py``. These tests pin the two
contracts that make the donor module safe to call from a mutation site:

  * the ledger is TELEMETRY, NOT A GATE — a broken ledger never blocks or
    breaks the mutation it describes, and
  * ``rollback_entry`` FAILS CLOSED — it changes nothing unless every
    before-blob exists and the pre-rollback safety capture succeeded.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from jaeger_agent.skill_registry import skill_ledger as led


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    """A bound instance layout rooted at tmp_path."""
    from jaeger_ai.core.instance.instance import InstanceLayout

    layout = InstanceLayout(root=tmp_path)
    layout.skills_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("jaeger_agent.workspace.get_layout", lambda: layout)
    monkeypatch.delenv("JAEGER_SKILL_LEDGER", raising=False)
    return layout


def _skill(layout, name: str, body: str = "v1") -> Path:
    folder = layout.skills_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(body, encoding="utf-8")
    return folder


# ---------------------------------------------------------------------------
# Blob store
# ---------------------------------------------------------------------------

def test_blobs_are_content_addressed_and_deduped(instance):
    a = led._store_blob(b"same bytes")
    b = led._store_blob(b"same bytes")
    assert a == b
    assert len(list(led.blobs_dir().iterdir())) == 1
    assert led.read_blob(a) == b"same bytes"


def test_read_blob_rejects_non_hex(instance):
    assert led.read_blob("../../etc/passwd") is None
    assert led.read_blob("") is None
    assert led.read_blob("zz") is None


# ---------------------------------------------------------------------------
# Append + read
# ---------------------------------------------------------------------------

def test_record_mutation_round_trip(instance):
    folder = _skill(instance, "demo", "before")
    before = led.capture_before(folder)
    (folder / "SKILL.md").write_text("after", encoding="utf-8")
    entry_id = led.record_mutation("edit", "demo", before=before, after_root=folder)

    assert entry_id
    rows = led.list_entries(skill="demo")
    assert len(rows) == 1
    assert rows[0]["id"] == entry_id
    assert rows[0]["action"] == "edit"
    assert rows[0]["actor"] == led.ACTOR_AGENT


def test_entries_are_newest_first(instance):
    _skill(instance, "demo")
    for i in range(3):
        led.append_entry("edit", "demo", evidence={"n": i})
    rows = led.list_entries(skill="demo")
    assert [r["evidence"]["n"] for r in rows] == [2, 1, 0]


def test_malformed_lines_are_skipped(instance):
    _skill(instance, "demo")
    led.append_entry("edit", "demo")
    with open(led.ledger_path(), "a", encoding="utf-8") as fh:
        fh.write("{not json\n\n")
    assert len(led.list_entries()) == 1


def test_actor_override(instance):
    _skill(instance, "demo")
    token = led.set_ledger_actor(led.ACTOR_CURATOR)
    try:
        eid = led.append_entry("archive", "demo")
    finally:
        led.reset_ledger_actor(token)
    assert led.get_entry(eid)["actor"] == led.ACTOR_CURATOR
    # Override is context-scoped, not sticky.
    assert led.get_entry(led.append_entry("edit", "demo"))["actor"] == led.ACTOR_AGENT


def test_disabled_by_env(instance, monkeypatch):
    monkeypatch.setenv("JAEGER_SKILL_LEDGER", "0")
    assert led.ledger_enabled() is False
    assert led.append_entry("edit", "demo") is None
    assert led.record_mutation("edit", "demo") is None
    assert led.capture_before(Path(".")) is None


# ---------------------------------------------------------------------------
# Telemetry-not-a-gate contract
# ---------------------------------------------------------------------------

def test_append_never_raises_when_ledger_unwritable(instance):
    _skill(instance, "demo")
    with mock.patch.object(led, "ledger_path", side_effect=OSError("boom")):
        assert led.append_entry("edit", "demo") is None  # logged, swallowed


def test_record_mutation_never_raises_on_capture_failure(instance):
    with mock.patch.object(led, "snapshot_paths", side_effect=OSError("boom")):
        assert led.record_mutation("edit", "demo", after_root=Path(".")) is None


def test_archive_still_works_when_ledger_is_broken(instance):
    """The donor's central promise: a ledger failure never blocks a mutation."""
    from jaeger_agent.skill_registry import curator

    folder = _skill(instance, "doomed")
    archive_dir = instance.root / "skills_archived"
    with mock.patch.object(led, "record_mutation", side_effect=RuntimeError("nope")), \
         mock.patch.object(led, "capture_before", side_effect=RuntimeError("nope")):
        with pytest.raises(RuntimeError):
            # Direct call proves the mock bites...
            led.capture_before(folder)
        # ...and the real call site must survive it.
        with mock.patch.object(curator._ledger, "capture_before", return_value=None), \
             mock.patch.object(curator._ledger, "record_mutation", return_value=None):
            dest = curator.archive_skill(folder, archive_dir=archive_dir)
    assert dest.exists()
    assert not folder.exists()


# ---------------------------------------------------------------------------
# Rollback — fail-closed
# ---------------------------------------------------------------------------

def test_rollback_restores_edited_file(instance):
    folder = _skill(instance, "demo", "original")
    before = led.capture_before(folder)
    (folder / "SKILL.md").write_text("mutated", encoding="utf-8")
    eid = led.record_mutation("edit", "demo", before=before, after_root=folder)

    ok, msg = led.rollback_entry(eid)
    assert ok, msg
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == "original"


def test_rollback_removes_files_the_mutation_created(instance):
    folder = _skill(instance, "demo", "original")
    before = led.capture_before(folder)
    (folder / "EXTRA.md").write_text("new file", encoding="utf-8")
    eid = led.record_mutation("edit", "demo", before=before, after_root=folder)

    ok, _ = led.rollback_entry(eid)
    assert ok
    assert not (folder / "EXTRA.md").exists()
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == "original"


def test_rollback_is_itself_undoable(instance):
    folder = _skill(instance, "demo", "v1")
    before = led.capture_before(folder)
    (folder / "SKILL.md").write_text("v2", encoding="utf-8")
    eid = led.record_mutation("edit", "demo", before=before, after_root=folder)

    ok, msg = led.rollback_entry(eid)
    assert ok and "Safety entry" in msg
    safety = [r for r in led.list_entries() if r["action"] == "pre-rollback"]
    assert len(safety) == 1
    # The safety entry captured v2, so rolling *it* back returns us to v2.
    ok2, _ = led.rollback_entry(safety[0]["id"])
    assert ok2
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == "v2"


def test_rollback_aborts_when_a_blob_is_missing(instance):
    folder = _skill(instance, "demo", "original")
    before = led.capture_before(folder)
    (folder / "SKILL.md").write_text("mutated", encoding="utf-8")
    eid = led.record_mutation("edit", "demo", before=before, after_root=folder)

    for blob in led.blobs_dir().iterdir():
        blob.unlink()

    ok, msg = led.rollback_entry(eid)
    assert not ok
    assert "nothing was changed" in msg
    # Untouched.
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == "mutated"


def test_rollback_aborts_when_safety_capture_fails(instance):
    folder = _skill(instance, "demo", "original")
    before = led.capture_before(folder)
    (folder / "SKILL.md").write_text("mutated", encoding="utf-8")
    eid = led.record_mutation("edit", "demo", before=before, after_root=folder)

    with mock.patch.object(led, "append_entry", return_value=None):
        ok, msg = led.rollback_entry(eid)
    assert not ok
    assert "were not changed" in msg
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == "mutated"


def test_rollback_refuses_paths_outside_the_instance(instance, tmp_path):
    """A hand-edited ledger must not become a write-anywhere primitive."""
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("do not touch", encoding="utf-8")
    sha = led._store_blob(b"evil")
    entry = {
        "id": "deadbeef", "ts": "now", "actor": "user", "action": "edit",
        "skill": "x", "evidence": {},
        "before": [{"path": str(outside), "sha256": sha}], "after": [],
    }
    path = led.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    ok, msg = led.rollback_entry("deadbeef")
    assert not ok
    assert "outside" in msg
    assert outside.read_text(encoding="utf-8") == "do not touch"


def test_rollback_unknown_id(instance):
    ok, msg = led.rollback_entry("nope")
    assert not ok and "no ledger entry" in msg


# ---------------------------------------------------------------------------
# Call-site wiring
# ---------------------------------------------------------------------------

def test_archive_skill_writes_a_ledger_entry(instance):
    from jaeger_agent.skill_registry import curator

    folder = _skill(instance, "stale", "content")
    curator.archive_skill(folder, archive_dir=instance.root / "skills_archived")

    rows = led.list_entries(skill="stale")
    assert len(rows) == 1
    assert rows[0]["action"] == "archive"
    # The before-manifest holds the pre-move contents, which is the whole
    # point — the source path no longer exists after the move.
    assert any(r["path"].endswith("SKILL.md") for r in rows[0]["before"])


def test_archived_skill_is_recoverable_from_the_ledger(instance):
    from jaeger_agent.skill_registry import curator

    folder = _skill(instance, "stale", "precious")
    curator.archive_skill(folder, archive_dir=instance.root / "skills_archived")
    assert not folder.exists()

    eid = led.list_entries(skill="stale")[0]["id"]
    ok, msg = led.rollback_entry(eid)
    assert ok, msg
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == "precious"
