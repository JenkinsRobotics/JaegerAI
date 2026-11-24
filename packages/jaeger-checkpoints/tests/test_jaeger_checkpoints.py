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
