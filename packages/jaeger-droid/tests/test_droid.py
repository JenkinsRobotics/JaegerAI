"""Tests for standalone jaeger-droid package (Host Gimbal Camera + Mic + Speakers EmbodimentPort)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from jaeger_contracts import EmbodimentPort
from jaeger_droid import HostDroidEmbodiment, discover_host_peripherals
from jaeger_droid.host_droid import PARK_PAN_DEG, PARK_TILT_DEG, _parse_system_profiler_devices


@pytest.fixture(autouse=True)
def _isolate_droid_hardware(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Guarantee unit tests never touch ~/.jaeger/droid/bin/droid-ptz or move the physical camera."""
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("jaeger_droid.host_droid.shutil.which", lambda _name: None)


def _install_fake_droid_ptz(tmp_path: Path) -> Path:
    ptz = tmp_path / "droid" / "bin" / "droid-ptz"
    ptz.parent.mkdir(parents=True, exist_ok=True)
    ptz.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ptz.chmod(0o755)
    return ptz


class _FakeStreamProc:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.killed = False

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_host_droid_parser_embodiment_and_estop() -> None:
    sample = """
Camera:

    Insta360 Link 2:

      Model ID: UVC Camera VendorID_11802 ProductID_19460
      Unique ID: 0x11000002e1a4c04
"""
    cams = _parse_system_profiler_devices(sample, kind="camera")
    assert len(cams) == 1
    assert cams[0]["name"] == "Insta360 Link 2"
    assert cams[0]["gimbal_capable"] is True

    droid = HostDroidEmbodiment(probe_on_init=False)
    assert isinstance(droid, EmbodimentPort)

    # Clamps pan/tilt safely
    r = droid.act("look_at", {"pan_deg": 400, "tilt_deg": -200, "zoom": 2.0})
    assert r["ok"] is True
    assert r["pose"]["pan_deg"] == 145.0 and r["pose"]["tilt_deg"] == -90.0

    # E-Stop blocks gimbal movement fail-closed
    droid.estop("privacy_shutter")
    blocked = droid.act("look_at", {"pan_deg": 10})
    assert blocked["ok"] is False and "estop" in blocked["error"]
    droid.release_estop()
    assert droid.act("center")["ok"] is True


def test_droid_ptz_resolution_dispatch_math_and_info(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ptz = _install_fake_droid_ptz(tmp_path)
    peripherals = discover_host_peripherals(probe_system=False)
    assert peripherals["tools"]["droid_ptz"] is True

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        if cmd[1] == "info":
            payload = {
                "ok": True,
                "pantilt_cur": [0, -306000],
                "pantilt_min": [-522000, -324000],
                "pantilt_max": [522000, 360000],
                "zoom_cur": 100,
            }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr("jaeger_droid.host_droid.subprocess.run", fake_run)

    droid = HostDroidEmbodiment(probe_on_init=False)

    # -35° pan -> -126000 arc-seconds; zoom unchanged (1.0) so no zoom command issued
    r = droid.act("look_at", {"pan_deg": -35.0, "tilt_deg": 0.0})
    assert r["ok"] is True and r["hardware_dispatched"] is True
    assert calls == [[str(ptz), "abs", "-126000", "0"]]
    calls.clear()

    # Zoom change dispatches both abs and zoom
    r_zoom = droid.act("look_at", {"pan_deg": 10.0, "tilt_deg": 5.0, "zoom": 2.5})
    assert r_zoom["ok"] is True and r_zoom["hardware_dispatched"] is True
    assert calls == [
        [str(ptz), "abs", "36000", "18000"],
        [str(ptz), "zoom", "250"],
    ]
    calls.clear()

    # Sleep parks at pan=0°, tilt=-85° (-306000 arcsec) and resets zoom back from 2.5 -> 100
    slept = droid.sleep("operator")
    assert slept["ok"] is True and slept["hardware_dispatched"] is True
    assert slept["pose"]["pan_deg"] == PARK_PAN_DEG and slept["pose"]["tilt_deg"] == PARK_TILT_DEG
    assert calls == [
        [str(ptz), "abs", "0", "-306000"],
        [str(ptz), "zoom", "100"],
    ]
    calls.clear()

    # Repeated sleep with zoom already 1.0 only issues abs 0 -306000
    droid.sleep("repeat")
    assert calls == [[str(ptz), "abs", "0", "-306000"]]
    calls.clear()

    # Wake always centers (abs 0 0) and resets zoom (zoom 100)
    woke = droid.wake("operator")
    assert woke["ok"] is True and woke["hardware_dispatched"] is True
    assert calls == [
        [str(ptz), "abs", "0", "0"],
        [str(ptz), "zoom", "100"],
    ]
    calls.clear()

    # Center always issues abs 0 0 + zoom 100
    centered = droid.act("center")
    assert centered["ok"] is True and centered["hardware_dispatched"] is True
    assert calls == [
        [str(ptz), "abs", "0", "0"],
        [str(ptz), "zoom", "100"],
    ]
    calls.clear()

    # read_gimbal_pose parses droid-ptz info JSON safely
    pose = droid.read_gimbal_pose()
    assert pose is not None
    assert pose["pan_deg"] == 0.0
    assert pose["tilt_deg"] == -85.0
    assert pose["zoom"] == 1.0


def test_droid_ptz_rejects_ok_false_and_falls_back_to_linkctl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ptz = _install_fake_droid_ptz(tmp_path)
    monkeypatch.setattr(
        "jaeger_droid.host_droid.subprocess.run",
        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 0, stdout='{"ok": false, "error": "no_device"}', stderr=""),
    )
    droid = HostDroidEmbodiment(probe_on_init=False)
    res = droid.act("look_at", {"pan_deg": 15.0})
    assert res["ok"] is True and res["hardware_dispatched"] is False

    # Remove droid-ptz and verify fallback to linkctl
    ptz.unlink()
    fallback_cmds: list[list[str]] = []
    monkeypatch.setattr(
        "jaeger_droid.host_droid.shutil.which",
        lambda name: "/usr/local/bin/linkctl" if name == "linkctl" else None,
    )
    monkeypatch.setattr(
        "jaeger_droid.host_droid.subprocess.run",
        lambda cmd, **_kw: (fallback_cmds.append(list(cmd)), subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))[1],
    )
    res_fb = droid.act("center")
    assert res_fb["hardware_dispatched"] is True
    assert fallback_cmds == [["/usr/local/bin/linkctl", "reset"]]


@pytest.mark.asyncio
async def test_droid_sleep_parks_kills_stream_and_blocks_camera_and_actions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ptz = _install_fake_droid_ptz(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "jaeger_droid.host_droid.subprocess.run",
        lambda cmd, **_kw: (calls.append(list(cmd)), subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr=""))[1],
    )

    droid = HostDroidEmbodiment(probe_on_init=False)
    obs0 = droid.observe()
    assert obs0["awake"] is True and obs0["sleeping"] is False and obs0["camera"] == "ready"

    fake_proc = _FakeStreamProc()
    droid._active_stream_proc = fake_proc  # type: ignore[assignment]
    assert droid.observe()["camera"] == "streaming"

    parked = droid.act("park", {"reason": "voice_sleep"})
    assert parked["ok"] is True
    assert parked["action"] == "sleep"
    assert parked["awake"] is False
    assert parked["sleeping"] is True
    assert parked["camera"] == "parked"
    assert parked["reason"] == "voice_sleep"
    assert parked["pose"] == {"pan_deg": 0.0, "tilt_deg": -85.0, "zoom": 1.0, "tracking": False}
    assert parked["hardware_dispatched"] is True
    assert fake_proc.killed is True
    assert calls == [[str(ptz), "abs", "0", "-306000"]]

    obs_asleep = droid.observe()
    assert obs_asleep["awake"] is False and obs_asleep["sleeping"] is True and obs_asleep["camera"] == "parked"

    # Guarded while sleeping
    assert droid.capture_frame() == {"ok": False, "error": "droid_sleeping"}
    assert droid.act("look_at", {"pan_deg": 20.0}) == {"ok": False, "error": "droid_sleeping"}
    assert droid.act("center") == {"ok": False, "error": "droid_sleeping"}
    assert droid.act("track_person", {"enabled": True}) == {"ok": False, "error": "droid_sleeping"}

    # stream_camera returns immediately without touching ffmpeg
    spawned = False

    async def _fail_if_spawned(*_a: Any, **_kw: Any) -> Any:
        nonlocal spawned
        spawned = True
        raise AssertionError("ffmpeg must not start while Droid is sleeping")

    monkeypatch.setattr("jaeger_droid.host_droid.shutil.which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr("jaeger_droid.host_droid.asyncio.create_subprocess_exec", _fail_if_spawned)
    frames = [frame async for frame in droid.stream_camera()]
    assert frames == []
    assert spawned is False


def test_droid_sleep_always_succeeds_under_estop_and_wake_is_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ptz = _install_fake_droid_ptz(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "jaeger_droid.host_droid.subprocess.run",
        lambda cmd, **_kw: (calls.append(list(cmd)), subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr=""))[1],
    )

    droid = HostDroidEmbodiment(probe_on_init=False)
    fake_proc = _FakeStreamProc()
    droid._active_stream_proc = fake_proc  # type: ignore[assignment]

    estop_res = droid.estop("operator_emergency")
    assert estop_res["ok"] is True and estop_res["estop_latched"] is True
    assert fake_proc.killed is True

    # Sleep / park MUST NEVER be blocked by E-Stop
    slept = droid.sleep("emergency_privacy")
    assert slept["ok"] is True
    assert slept["awake"] is False
    assert slept["sleeping"] is True
    assert slept["camera"] == "parked"
    assert slept["hardware_dispatched"] is True
    assert calls == [[str(ptz), "abs", "0", "-306000"]]
    calls.clear()

    assert droid.act("sleep", {"reason": "estop_act"})["ok"] is True
    assert droid.act("park", {"reason": "estop_park"})["ok"] is True
    calls.clear()

    # Wake MUST be blocked fail-closed while E-Stop is latched
    blocked_wake = droid.wake("operator")
    assert blocked_wake["ok"] is False
    assert blocked_wake["error"] == "estop_latched:operator_emergency"
    assert blocked_wake["awake"] is False
    assert blocked_wake["sleeping"] is True
    assert calls == []

    blocked_act_wake = droid.act("wake")
    assert blocked_act_wake["ok"] is False
    assert "estop_latched" in blocked_act_wake["error"]

    # After releasing E-Stop, wake succeeds and centers gimbal
    droid.release_estop()
    woke = droid.wake("operator")
    assert woke["ok"] is True
    assert woke["action"] == "wake"
    assert woke["awake"] is True
    assert woke["sleeping"] is False
    assert woke["camera"] == "ready"
    assert woke["pose"] == {"pan_deg": 0.0, "tilt_deg": 0.0, "zoom": 1.0, "tracking": False}
    assert woke["hardware_dispatched"] is True
    assert calls == [
        [str(ptz), "abs", "0", "0"],
        [str(ptz), "zoom", "100"],
    ]


def test_droid_sync_hardware_state_detects_parked_camera_and_face_tracking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ptz = _install_fake_droid_ptz(tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        if len(cmd) > 1 and cmd[1] == "info":
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout=json.dumps({"ok": True, "pantilt_cur": [0, -306000], "zoom_cur": 100}),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr("jaeger_droid.host_droid.subprocess.run", fake_run)
    droid = HostDroidEmbodiment(probe_on_init=False)
    pose = droid.sync_hardware_state()
    assert pose is not None and pose["tilt_deg"] == -85.0
    obs = droid.observe()
    assert obs["sleeping"] is True and obs["awake"] is False and obs["camera"] == "parked"
    assert obs["voice_enrolled"] is False

    # Wake, enable face tracking, and verify proportional gimbal step
    droid.wake("operator")
    calls.clear()
    droid.act("track_person", {"enabled": True})
    droid._step_face_tracking((0.25, -0.20))  # noqa: SLF001
    assert any(c[1] == "abs" for c in calls)
    assert droid.observe()["pose"]["pan_deg"] < 0.0
    assert droid.observe()["pose"]["tilt_deg"] > 0.0
