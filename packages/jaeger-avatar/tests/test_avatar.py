"""Unit tests for jaeger-avatar (VRM 0.x/1.0 GLB inspection, asset store, live emotion, Kokoro visemes)."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from jaeger_avatar import AvatarStore, build_viseme_timeline, inspect_avatar_bytes


def _make_minimal_vrm_glb(*, vrm_version: int = 1) -> bytes:
    ext = (
        {"VRMC_vrm": {"specVersion": "1.0", "meta": {"name": "JaegerVRM"}, "expressions": {"preset": {"happy": {}, "aa": {}}}}}
        if vrm_version == 1
        else {"VRM": {"specVersion": "0.0", "meta": {"title": "LegacyVRM0"}, "blendShapeMaster": {"blendShapeGroups": [{"presetName": "joy"}]}}}
    )
    doc = {
        "asset": {"version": "2.0", "generator": "jaeger-test"},
        "extensionsUsed": list(ext.keys()),
        "extensions": ext,
        "accessors": [{"count": 300}],
        "meshes": [{"primitives": [{"mode": 4, "indices": 0}]}],
    }
    chunk = json.dumps(doc).encode("utf-8")
    while len(chunk) % 4:
        chunk += b" "
    header = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(chunk))
    ch_hdr = struct.pack("<II", len(chunk), 0x4E4F534A)
    return header + ch_hdr + chunk


def test_accepts_both_vrm0_and_vrm1_and_stores_assets(tmp_path: Path) -> None:
    vrm1 = _make_minimal_vrm_glb(vrm_version=1)
    vrm0 = _make_minimal_vrm_glb(vrm_version=0)

    info1 = inspect_avatar_bytes(vrm1, "jaeger.vrm")
    assert info1["format"] == "vrm" and info1["vrm_major"] == 1 and info1["triangles"] == 100
    assert "happy" in info1["expressions"]

    info0 = inspect_avatar_bytes(vrm0, "companion.vrm")
    assert info0["format"] == "vrm" and info0["vrm_major"] == 0
    assert "joy" in info0["expressions"]

    store = AvatarStore(tmp_path)
    rec = store.add_asset(vrm1, "jaeger.vrm")
    assert store.get_asset_file(rec["sha256"]) is not None

    bound = store.set_agent_avatar("jaeger", asset_sha=rec["sha256"], mode="3d_vrm", display_name="Jaeger")
    assert bound["avatar"]["mode"] == "3d_vrm"
    assert bound["asset"]["sha256"] == rec["sha256"]

    live = store.set_live_state("jaeger", emotion="focused", intensity=0.9, state="speaking", amplitude=0.6)
    assert live["emotion"] == "focused" and live["amplitude"] == 0.6


def test_viseme_timeline_uses_kokoro_marks_and_grapheme_fallback() -> None:
    real = build_viseme_timeline("hello world", kokoro_marks=[[0.1, 0.16, "p"], [0.3, 0.38, "f"]], duration_s=0.8)
    assert real["source"] == "kokoro_lip_marks" and real["stub"] is False
    assert len(real["frames"]) == 2
    assert real["frames"][0]["viseme"] == "closed"

    fallback = build_viseme_timeline("Hello from Jaeger!")
    assert fallback["source"] == "grapheme_vrm5" and fallback["stub"] is False
    assert any(f["viseme"] == "aa" for f in fallback["frames"])
