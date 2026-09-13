from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.audio_devices import (
    describe_input_devices,
    select_input_device,
)


class _SoundDevice:
    def __init__(self, devices, default_input=-1):
        self._devices = devices
        self.default = SimpleNamespace(device=[default_input, -1])

    def query_devices(self):
        return self._devices


def _device(name, inputs, latency=0.01, rate=48_000):
    return {
        "name": name,
        "max_input_channels": inputs,
        "default_low_input_latency": latency,
        "default_samplerate": rate,
    }


def test_system_default_and_explicit_microphone_are_detected():
    sd = _SoundDevice([
        _device("iPhone Microphone", 1, latency=0.128),
        _device("Insta360 Link 2", 1, latency=0.004),
        _device("Speakers", 0),
    ], default_input=0)
    selected, devices = select_input_device(sounddevice_module=sd)
    assert selected["name"] == "iPhone Microphone"
    assert selected["default"] is True
    selected, _ = select_input_device("insta360", sounddevice_module=sd)
    assert selected["index"] == 1
    assert "input latency 4.0 ms" in describe_input_devices(devices)[1]


def test_missing_microphone_has_an_explicit_error():
    sd = _SoundDevice([_device("Speakers", 0)])
    with pytest.raises(RuntimeError, match="No microphone detected"):
        select_input_device(sounddevice_module=sd)


def test_unknown_microphone_lists_detected_choices():
    sd = _SoundDevice([_device("Insta360 Link 2", 1)], default_input=0)
    with pytest.raises(RuntimeError, match="Detected: 0: Insta360 Link 2"):
        select_input_device("missing", sounddevice_module=sd)
