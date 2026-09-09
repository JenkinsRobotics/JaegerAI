"""Unit tests for jaeger start, stop, restart, and status lifecycle verbs."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from jaeger_ai.cli.verbs import lifecycle_verbs


def test_status_json_output(capsys, monkeypatch):
    monkeypatch.setattr(lifecycle_verbs, "_get_launchd_jobs", lambda: {
        "com.jenkinsrobotics.jaeger-bridge": {"pid": 1234, "status": 0},
    })
    monkeypatch.setattr(lifecycle_verbs, "_find_app_pids", lambda: [5678])
    monkeypatch.setattr(lifecycle_verbs, "_get_containers_state", lambda: {
        "jaeger-hermes-webui": {"state": "running", "ip": "192.168.64.10", "image": "img"},
        "jaeger-openclaw": {"state": "stopped", "ip": "—", "image": "img"},
    })
    monkeypatch.setattr(lifecycle_verbs, "_is_port_open", lambda port, host="127.0.0.1", timeout=0.5: port == 8791)

    rc = lifecycle_verbs._cmd_status_argv(["--json"])
    assert rc == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["app"]["running"] is True
    assert data["app"]["pids"] == [5678]
    assert any(s["name"] == "Jaeger Bridge" and s["running"] is True for s in data["services"])
    assert any(c["name"] == "jaeger-hermes-webui" and c["state"] == "running" for c in data["containers"])


def test_status_terminal_output(capsys, monkeypatch):
    monkeypatch.setattr(lifecycle_verbs, "_get_launchd_jobs", lambda: {})
    monkeypatch.setattr(lifecycle_verbs, "_find_app_pids", lambda: [])
    monkeypatch.setattr(lifecycle_verbs, "_get_containers_state", lambda: {})
    monkeypatch.setattr(lifecycle_verbs, "_is_port_open", lambda *a, **kw: False)

    rc = lifecycle_verbs._cmd_status_argv([])
    assert rc == 0

    captured = capsys.readouterr()
    assert "Jaeger AI Fabric Status" in captured.out
    assert "Desktop App:" in captured.out
    assert "Host Services:" in captured.out
    assert "Linux Containers:" in captured.out


def test_stop_dry_run(capsys, monkeypatch):
    monkeypatch.setattr(lifecycle_verbs, "_get_launchd_jobs", lambda: {
        lifecycle_verbs.SUPERVISOR_SERVICE: {"pid": 999, "status": 0},
        "com.jenkinsrobotics.jaeger-bridge": {"pid": 1000, "status": 0},
    })
    monkeypatch.setattr(lifecycle_verbs, "_find_app_pids", lambda: [888])
    monkeypatch.setattr(lifecycle_verbs, "_get_containers_state", lambda: {
        "jaeger-hermes-webui": {"state": "running", "ip": "192.168.64.10", "image": "img"},
    })

    rc = lifecycle_verbs._cmd_stop_argv(["--dry-run"])
    assert rc == 0

    captured = capsys.readouterr()
    assert "Stopping Jaeger AI stack..." in captured.out
    assert "[dry-run]" in captured.out
    assert "Would terminate JaegerAI.app" in captured.out
    assert f"Would bootout {lifecycle_verbs.SUPERVISOR_SERVICE}" in captured.out


def test_start_dry_run(capsys):
    rc = lifecycle_verbs._cmd_start_argv(["--dry-run"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Starting Jaeger AI stack..." in captured.out
    assert "[dry-run]" in captured.out


def test_status_checks_container_native_api_at_container_address(monkeypatch):
    calls = []
    monkeypatch.setattr(lifecycle_verbs, "_is_port_open", lambda port, host="127.0.0.1", timeout=0.5: calls.append((host, port)) or True)
    containers = {"jaeger-hermes-webui": {"state": "running", "ip": "192.168.64.71/24", "image": "img"}}
    assert lifecycle_verbs._service_port_open(
        "com.jenkinsrobotics.hermes-native-api", 8645, containers,
    ) is True
    assert calls == [("192.168.64.71", 8645)]


def test_start_does_not_rewrite_installed_profile_configuration(capsys):
    # Dry-run follows the same configuration branch and must advertise the
    # preservation contract instead of invoking adapter setup/install.
    assert lifecycle_verbs._cmd_start_argv(["--dry-run", "--no-app", "--no-containers"]) == 0
    assert "Preserving installed configurations" in capsys.readouterr().out
