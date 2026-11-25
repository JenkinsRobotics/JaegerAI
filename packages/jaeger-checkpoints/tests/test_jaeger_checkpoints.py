from __future__ import annotations

from jaeger_checkpoints import ShadowCheckpointStore


def test_shadow_checkpoint_snapshot_diff_and_restore(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    f = ws / "app.py"
    f.write_text("x = 1\n", encoding="utf-8")

    store = ShadowCheckpointStore(tmp_path / "shadow_store")
    cp1 = store.snapshot(ws, label="before edit")
    assert cp1.checkpoint_id
    assert not (ws / ".git").exists()  # zero pollution of user workspace

    f.write_text("x = 999\n", encoding="utf-8")
    diff = store.diff(ws, cp1.checkpoint_id)
    assert "-x = 1" in diff and "+x = 999" in diff

    res = store.restore(ws, cp1.checkpoint_id)
    assert res["ok"] is True
    assert f.read_text(encoding="utf-8") == "x = 1\n"
    assert len(store.list_checkpoints(ws)) >= 2


def test_turn_diff_tracker_computes_net_diffs_and_renames():
    from jaeger_checkpoints import TurnDiffTracker

    tracker = TurnDiffTracker()
    tracker.record_edit("src/a.py", before="a = 1\n", after="a = 2\n")
    tracker.record_edit("src/a.py", before="a = 2\n", after="a = 3\n")
    tracker.record_edit("src/b.py", before="a = 3\n", after="a = 4\n", renamed_from="src/a.py")
    assert tracker.changed_files() == ["src/b.py"]
    diff = tracker.unified_diff()
    assert "--- a/src/a.py" in diff and "+++ b/src/b.py" in diff
    assert "-a = 1" in diff and "+a = 4" in diff
    tracker.reset()
    assert tracker.changed_files() == []
