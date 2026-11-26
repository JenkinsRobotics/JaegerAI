"""Tests for standalone jaeger-droid package (Host Gimbal Camera + Mic + Speakers EmbodimentPort)."""

from __future__ import annotations

from jaeger_contracts import EmbodimentPort
from jaeger_droid import HostDroidEmbodiment
from jaeger_droid.host_droid import _parse_system_profiler_devices


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
