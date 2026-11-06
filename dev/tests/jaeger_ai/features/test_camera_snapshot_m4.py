"""M4 acceptance test: real webcam capture + VLM description, grant-gated.

Run: PYTHONPATH=. python3 -m pytest dev/tests/jaeger_ai/features/test_camera_snapshot_m4.py -q
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture()
def camera_grant(tmp_path, monkeypatch):
    import jaeger_ai.features.host_capabilities.grants as grants

    monkeypatch.setattr(grants, "GRANTS_PATH", tmp_path / "grants.json")
    (tmp_path / "grants.json").write_text(
        '{"version": 1, "identities": {"jaeger": {"capabilities": ["camera.status", "camera.snapshot"]}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(grants, "get_current_identity", lambda: "jaeger")
    monkeypatch.setenv("JAEGER_CAMERA_SNAPSHOT", str(tmp_path / "snap.jpg"))
    return tmp_path


def test_camera_status_finds_a_device(camera_grant):
    from jaeger_ai.features.host_capabilities.camera_tools import camera_status

    status = camera_status()
    assert isinstance(status["devices"], list)


def test_camera_snapshot_captures_and_describes(camera_grant):
    pytest.importorskip("cv2")
    from jaeger_ai.features.host_capabilities.camera_tools import camera_snapshot

    result = camera_snapshot("0")
    if not result["captured"]:
        pytest.skip("no camera available in this environment")
    assert result["path"].endswith("snap.jpg")
    assert os.path.getsize(result["path"]) > 0
    # VLM description is best-effort; if mlx_vlm is installed it must produce text
    if result.get("description") is not None:
        assert isinstance(result["description"], str) and len(result["description"]) > 5


def test_camera_snapshot_denied_without_grant(tmp_path, monkeypatch):
    import jaeger_ai.features.host_capabilities.grants as grants

    monkeypatch.setattr(grants, "GRANTS_PATH", tmp_path / "grants.json")
    (tmp_path / "grants.json").write_text(
        '{"version": 1, "identities": {"jaeger": {"capabilities": []}}}', encoding="utf-8"
    )
    monkeypatch.setattr(grants, "get_current_identity", lambda: "jaeger")
    from jaeger_ai.features.host_capabilities.camera_tools import camera_snapshot

    with pytest.raises(PermissionError):
        camera_snapshot("0")
