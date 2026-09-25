"""What is plugged into this machine.

The control plane inspects a RUNNING system. This answers the question
that comes first — which device index is the ring mic, which tty is the
motor controller — that you previously had to already know.
"""

from __future__ import annotations

import time

from jaeger_os.hardware import scan as scan_mod


def test_a_scan_returns_the_two_always_probed_kinds():
    result = scan_mod.scan()
    assert set(result) == {"audio", "serial"}


def test_cameras_are_opt_in():
    """Probing a camera OPENS it, which can blink a capture LED. A
    scan should not appear to spy on someone."""
    assert "cameras" not in scan_mod.scan()
    assert "cameras" in scan_mod.scan(include_cameras=True)


def test_a_probe_that_hangs_does_not_hang_the_scan():
    """The failure this exists for, and it is not hypothetical — audio
    enumeration goes into a C library, and a wedged CoreAudio blocks
    forever with no way to interrupt it. A scanner that hangs is worse
    than one reporting nothing, because the hang is what you ran the
    scanner to diagnose."""
    original = scan_mod.PROBE_TIMEOUT_S
    scan_mod.PROBE_TIMEOUT_S = 0.3
    try:
        t0 = time.perf_counter()
        out = scan_mod._with_timeout(lambda: time.sleep(30), "stuck")
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"hung for {elapsed:.1f}s"
        assert "timed out" in out[0]["error"]
    finally:
        scan_mod.PROBE_TIMEOUT_S = original


def test_a_timeout_says_what_to_try():
    """An error that names the likely cause beats one that just says
    'failed' — this one has a known culprit on macOS."""
    original = scan_mod.PROBE_TIMEOUT_S
    scan_mod.PROBE_TIMEOUT_S = 0.2
    try:
        out = scan_mod._with_timeout(lambda: time.sleep(30), "audio")
        assert "coreaudiod" in out[0]["error"]
    finally:
        scan_mod.PROBE_TIMEOUT_S = original


def test_a_probe_that_raises_is_reported_not_propagated():
    def boom():
        raise OSError("no such backend")
    out = scan_mod._with_timeout(boom, "thing")
    assert "no such backend" in out[0]["error"]


def test_a_missing_backend_does_not_stop_the_others():
    """A headless box with no camera still lists its serial ports. A
    scanner that refuses to run because one backend is absent is a
    scanner nobody runs."""
    result = scan_mod.scan()
    assert isinstance(result["serial"], list)
    assert isinstance(result["audio"], list)


def test_json_output_is_valid(capsys):
    """The output an app author pastes into a manifest."""
    import json

    assert scan_mod.main(["--json"]) == 0
    json.loads(capsys.readouterr().out)
