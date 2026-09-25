from __future__ import annotations

import argparse
import inspect
import subprocess

from jaeger_whisper_stt import cli
from jaeger_whisper_stt.engine import bench


def test_device_probe_timeout_is_reported_not_hung(monkeypatch, capsys) -> None:
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["python"], timeout=0.1)

    monkeypatch.setattr(cli.subprocess, "run", timeout)
    result = cli._cmd_devices(argparse.Namespace(timeout=0.1, json=False))
    assert result == 1
    assert "timed out" in capsys.readouterr().err


def test_live_cli_rejects_wake_on_chunked_streaming_before_boot(capsys) -> None:
    args = argparse.Namespace(method="local_agreement", wake=True)
    assert cli._cmd_run(args) == 2
    assert "cannot apply" in capsys.readouterr().err


def test_benchmark_recording_has_no_second_sounddevice_path() -> None:
    assert "import sounddevice" not in inspect.getsource(bench._record)
