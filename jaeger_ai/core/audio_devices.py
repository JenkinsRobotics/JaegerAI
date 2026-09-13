"""Audio input discovery shared by headless voice entry points."""

from __future__ import annotations

from typing import Any


def input_devices(sounddevice_module: Any | None = None) -> list[dict[str, Any]]:
    """Return usable microphones with the system default marked."""
    sd = sounddevice_module
    if sd is None:
        import sounddevice as sd  # type: ignore[no-redef]

    try:
        default_pair = sd.default.device
        default_index = int(default_pair[0])
    except (AttributeError, IndexError, TypeError, ValueError):
        default_index = -1

    found: list[dict[str, Any]] = []
    for index, raw in enumerate(sd.query_devices()):
        info = dict(raw)
        if int(info.get("max_input_channels") or 0) < 1:
            continue
        found.append({
            "index": index,
            "name": str(info.get("name") or f"Input {index}"),
            "default": index == default_index,
            "sample_rate": float(info.get("default_samplerate") or 0.0),
            "low_latency_ms": round(
                float(info.get("default_low_input_latency") or 0.0) * 1000,
                1,
            ),
        })
    return found


def select_input_device(
    selector: str | int | None = None,
    *,
    sounddevice_module: Any | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve a microphone index/name, defaulting to the macOS selection."""
    devices = input_devices(sounddevice_module)
    if not devices:
        raise RuntimeError(
            "No microphone detected. Connect or enable an audio input device, "
            "then select it in System Settings → Sound → Input."
        )

    if selector is None or str(selector).strip() == "":
        return next((item for item in devices if item["default"]), devices[0]), devices

    token = str(selector).strip()
    if token.isdigit():
        index = int(token)
        for item in devices:
            if item["index"] == index:
                return item, devices

    folded = token.casefold()
    exact = [item for item in devices if item["name"].casefold() == folded]
    partial = [item for item in devices if folded in item["name"].casefold()]
    matches = exact or partial
    if len(matches) == 1:
        return matches[0], devices
    if len(matches) > 1:
        names = ", ".join(f"{item['index']}: {item['name']}" for item in matches)
        raise RuntimeError(f"Microphone {token!r} is ambiguous: {names}")
    choices = ", ".join(f"{item['index']}: {item['name']}" for item in devices)
    raise RuntimeError(f"Microphone {token!r} was not found. Detected: {choices}")


def describe_input_devices(devices: list[dict[str, Any]]) -> list[str]:
    """Human-readable device rows for terminal diagnostics."""
    return [
        (f"{item['index']}: {item['name']}"
         f" · {item['sample_rate']:.0f} Hz"
         f" · input latency {item['low_latency_ms']:.1f} ms"
         f"{' · system default' if item['default'] else ''}")
        for item in devices
    ]


__all__ = ["describe_input_devices", "input_devices", "select_input_device"]
