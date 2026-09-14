"""What hardware is attached to this machine.

    python3 -m jaeger_os.hardware.scan
    python3 -m jaeger_os.hardware.scan --json

The control plane can inspect a RUNNING system. Nothing could answer
the question that comes first: *what is plugged in, before I write the
manifest*. You had to already know — which device index is the ring
mic, which `/dev/tty.*` is the motor controller — and the usual way to
find out was trial and error against a robot.

Borrowed from Quantum Codex's `quantum-scan`, which prints what is
attached and emits JSON an app author pastes into a config.

**Every probe is optional, degrades, and CANNOT HANG.** A machine with
no serial library still lists its audio devices; a headless box with no
camera still lists its serial ports.

The timeout is not paranoia. Audio enumeration goes into a C library,
and a wedged CoreAudio — which a process killed mid-stream can cause,
and did on the machine this was written on — blocks forever with no way
to interrupt it. A scanner that hangs is worse than one that reports
nothing, because the hang is what you run the scanner to diagnose. Each
probe runs on a thread with a deadline and reports what it could not
reach.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from typing import Any, Callable

#: Long enough for a healthy backend, short enough that a wedged one
#: does not hold the tool. Audio enumeration on a working machine is
#: milliseconds; if it has not answered in this long it is not going to.
PROBE_TIMEOUT_S = 5.0


def _with_timeout(fn: Callable[[], list], what: str) -> list[dict[str, Any]]:
    """Run a probe, giving up rather than hanging.

    The worker thread is abandoned, not killed — a blocked C call
    cannot be interrupted from Python. It is a daemon, so it does not
    hold the process open, and leaking one thread to keep the tool
    usable is the right trade when the alternative is no output at all.
    """
    box: list[Any] = []
    done = threading.Event()

    def run() -> None:
        try:
            box.append(fn())
        except Exception as exc:  # noqa: BLE001
            box.append([{"error": f"{what} scan failed: {exc}"}])
        finally:
            done.set()

    threading.Thread(target=run, daemon=True, name=f"scan-{what}").start()
    if not done.wait(PROBE_TIMEOUT_S):
        return [{"error": f"{what} scan timed out after "
                          f"{PROBE_TIMEOUT_S:.0f}s — the backend is not "
                          f"responding (on macOS, a wedged CoreAudio "
                          f"does this; try `sudo killall coreaudiod`)"}]
    return box[0] if box else []


def audio_devices() -> list[dict[str, Any]]:
    """Microphones and speakers, with the INDEX a config needs.

    The index is the point. ``input_device: 2`` in a config is
    meaningless until something tells you what 2 is, and the name alone
    is not enough because two devices can share one.
    """
    try:
        import sounddevice as sd
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"sounddevice unavailable: {exc}"}]

    out: list[dict[str, Any]] = []
    try:
        default_in, default_out = sd.default.device
    except Exception:  # noqa: BLE001
        default_in = default_out = None

    try:
        for index, dev in enumerate(sd.query_devices()):
            entry = {
                "index": index,
                "name": dev.get("name", ""),
                "inputs": dev.get("max_input_channels", 0),
                "outputs": dev.get("max_output_channels", 0),
                "default_sample_rate": int(dev.get("default_samplerate", 0)),
            }
            if index == default_in:
                entry["default"] = "input"
            if index == default_out:
                entry["default"] = "output" if "default" not in entry else "both"
            out.append(entry)
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"audio scan failed: {exc}"}]
    return out


def serial_ports() -> list[dict[str, Any]]:
    """Serial devices — how a JP01 controller is reached.

    ``device`` is what goes in a config. ``hwid`` is what identifies it
    ACROSS reboots: a USB adapter's ``/dev/tty.usbserial-XXXX`` can move
    between ports, and pinning the path rather than the serial number is
    how a robot works until someone unplugs it.
    """
    try:
        from serial.tools import list_ports
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"pyserial unavailable: {exc}"}]

    try:
        return [{
            "device": p.device,
            "description": p.description,
            "hwid": p.hwid,
            "manufacturer": p.manufacturer or "",
            "serial_number": p.serial_number or "",
        } for p in list_ports.comports()]
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"serial scan failed: {exc}"}]


def cameras(limit: int = 6) -> list[dict[str, Any]]:
    """Cameras, by opening each index and asking.

    There is no portable enumeration, so this OPENS each index in turn,
    which is slow and can make a capture LED blink. Off by default for
    that reason — a scan should not appear to spy on someone.
    """
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"opencv unavailable: {exc}"}]

    found: list[dict[str, Any]] = []
    for index in range(limit):
        cap = None
        try:
            cap = cv2.VideoCapture(index)
            if not cap.isOpened():
                continue
            found.append({
                "index": index,
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": round(cap.get(cv2.CAP_PROP_FPS), 1),
            })
        except Exception:  # noqa: BLE001
            continue
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # noqa: BLE001
                    pass
    return found


def scan(*, include_cameras: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "audio": _with_timeout(audio_devices, "audio"),
        "serial": _with_timeout(serial_ports, "serial"),
    }
    if include_cameras:
        result["cameras"] = _with_timeout(cameras, "camera")
    return result


# ── printing ─────────────────────────────────────────────────────

def _print_human(result: dict[str, Any]) -> None:
    audio = result.get("audio") or []
    print("\naudio")
    if not audio or "error" in audio[0]:
        print(f"  {audio[0]['error'] if audio else 'none found'}")
    for dev in (d for d in audio if "error" not in d):
        kind = ("in/out" if dev["inputs"] and dev["outputs"]
                else "in" if dev["inputs"] else "out")
        mark = f"  <- default {dev['default']}" if "default" in dev else ""
        print(f"  [{dev['index']:2}] {dev['name'][:38]:38} {kind:6} "
              f"{dev['default_sample_rate']:6} Hz{mark}")

    ports = result.get("serial") or []
    print("\nserial")
    if not ports:
        print("  none found")
    elif "error" in ports[0]:
        print(f"  {ports[0]['error']}")
    for p in (x for x in ports if "error" not in x):
        print(f"  {p['device']:28} {p['description'][:40]}")
        if p["serial_number"]:
            print(f"  {'':28} sn={p['serial_number']}  "
                  f"(pin THIS, not the path)")

    if "cameras" in result:
        cams = result["cameras"]
        print("\ncameras")
        if not cams:
            print("  none found")
        for c in (x for x in cams if "error" not in x):
            print(f"  [{c['index']}] {c['width']}x{c['height']} @ {c['fps']} fps")
    print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="jaeger-scan",
        description="What hardware is attached to this machine.")
    p.add_argument("--json", action="store_true",
                   help="machine-readable, for pasting into a manifest")
    p.add_argument("--cameras", action="store_true",
                   help="probe camera indices too (slow; may blink a "
                        "capture LED, so it is off by default)")
    args = p.parse_args(argv)

    result = scan(include_cameras=args.cameras)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_human(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
