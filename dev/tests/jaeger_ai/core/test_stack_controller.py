"""Tests for jaeger stack orchestrator (jaeger_ai.core.runtime.stack)."""

import plistlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jaeger_ai.core.runtime.stack import (
    STACK_SERVICES,
    SERVICE_BY_ID,
    build_plist,
    sync_plists,
    stack_status,
    stack_down,
)


def test_build_plist_structure(tmp_path: Path):
    """Test generating launchd plist XML with environment and arguments."""
    gateway_def = SERVICE_BY_ID["gateway"]
    plist_xml = build_plist(gateway_def, commit_sha="abcdef1234567890")
    data = plistlib.loads(plist_xml.encode("utf-8"))
    assert data["Label"] == "com.jenkinsrobotics.jaeger-gateway"
    assert "jaeger_ai.core.gateway.server" in " ".join(data["ProgramArguments"])
    assert data["KeepAlive"] is True
    assert data["RunAtLoad"] is False
    assert data["EnvironmentVariables"]["JAEGER_GIT_COMMIT"] == "abcdef1234567890"
    assert "StandardOutPath" in data
    assert "StandardErrorPath" in data


def test_managed_bridge_is_always_a_gateway_client():
    bridge = plistlib.loads(build_plist(
        SERVICE_BY_ID["agent"], commit_sha="abcdef1234567890"
    ).encode("utf-8"))
    assert bridge["EnvironmentVariables"]["JAEGER_BRIDGE_EXECUTION"] == "gateway"
    ids = [service.id for service in STACK_SERVICES]
    assert ids.index("gateway") < ids.index("agent")


def test_gui_services_find_python_and_coding_workers(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr("jaeger_ai.core.runtime.stack._default_python", lambda: "/test/venv/bin/python")
    data = plistlib.loads(build_plist(SERVICE_BY_ID["gateway"]).encode())
    paths = data["EnvironmentVariables"]["PATH"].split(":")
    assert paths[0] == "/test/venv/bin"
    assert "/opt/homebrew/bin" in paths
    assert "/usr/local/bin" in paths
    assert len(paths) == len(set(paths))


def test_stack_up_reloads_loaded_job_configuration(monkeypatch):
    from jaeger_ai.core.runtime import stack

    commands = []
    monkeypatch.setattr(stack, "_launchctl", lambda args: commands.append(args) or MagicMock(returncode=0))
    monkeypatch.setattr(stack, "migrate_legacy_launchagents", lambda: None)
    monkeypatch.setattr(stack, "sync_plists", list)
    monkeypatch.setattr("jaeger_ai.core.frameworks.setup._configure_agent_models", lambda: None)
    monkeypatch.setattr(stack, "stack_status", lambda services: [{"ready": True}])
    service = SERVICE_BY_ID["gateway"]
    assert stack.stack_up([service])["ok"]
    actions = [command[0] for command in commands]
    assert actions == ["print", "bootout", "bootstrap", "kickstart"]


def test_sync_plists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test that plists for all services are written to launchd dir."""
    launchd_dir = tmp_path / "launchd"
    monkeypatch.setattr("jaeger_ai.core.runtime.stack._launchd_dir", lambda: launchd_dir)

    paths = sync_plists()
    assert len(paths) == len(STACK_SERVICES)
    for path in paths:
        assert path.exists()
        assert path.suffix == ".plist"
        data = plistlib.loads(path.read_bytes())
        assert data["Label"].startswith("com.jenkinsrobotics.")


def test_stack_status_structure(monkeypatch: pytest.MonkeyPatch):
    """Test stack_status aggregates service states."""
    # Mock launchctl
    def mock_launchctl(args):
        res = MagicMock()
        res.returncode = 0
        res.stdout = '{\n"PID" = 12345;\n"LastExitStatus" = 0;\n}'
        return res

    monkeypatch.setattr("jaeger_ai.core.runtime.stack._launchctl", mock_launchctl)
    monkeypatch.setattr("jaeger_ai.core.runtime.stack.probe_service_health", lambda service: True)

    statuses = stack_status()
    assert len(statuses) == len(STACK_SERVICES)
    ids = [s["id"] for s in statuses]
    assert "gateway" in ids
    assert "webui" in ids
    assert "agent" in ids


def test_stack_down_terminates_services(monkeypatch: pytest.MonkeyPatch):
    """Test stack down runs bootout and cleans up stragglers."""
    cmds = []

    def mock_launchctl(args):
        cmds.append(args)
        res = MagicMock()
        res.returncode = 0
        res.stdout = ""
        return res

    monkeypatch.setattr("jaeger_ai.core.runtime.stack._launchctl", mock_launchctl)
    monkeypatch.setattr("jaeger_ai.core.runtime.stack._find_straggler_pids", lambda: set())
    monkeypatch.setattr("jaeger_ai.core.runtime.stack.stack_status", lambda services=None: [])

    res = stack_down(wait_timeout=0.1)
    assert res["ok"] is True
    # Verify bootout was called for each service
    bootout_cmds = [c for c in cmds if c and c[0] == "bootout"]
    assert len(bootout_cmds) == len(STACK_SERVICES)
