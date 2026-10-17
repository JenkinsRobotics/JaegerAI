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
    assert data["KeepAlive"] == {"SuccessfulExit": False}  # crash-only restart
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
    monkeypatch.setattr("jaeger_ai.core.runtime.stack.stack_status", lambda services=None: [])

    res = stack_down(wait_timeout=0.1)
    assert res["ok"] is True
    # Verify bootout was called for each service
    bootout_cmds = [c for c in cmds if c and c[0] == "bootout"]
    assert len(bootout_cmds) == len(STACK_SERVICES)
    labels = {command[1].rsplit("/", 1)[-1] for command in bootout_cmds}
    assert "com.jenkinsrobotics.jaeger-gateway" in labels
    assert "com.jenkinsrobotics.jaeger-ollama-bridge" in labels
    source = Path("jaeger_ai/core/runtime/stack.py").read_text(encoding="utf-8")
    assert "pgrep" not in source
    assert "lsof" not in source


def _write_instance_config(root: Path, text: str) -> None:
    path = root / "instances" / "jaeger" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_plists_keep_operator_ollama_and_offline_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Regenerating plists keeps the operator's Ollama limits and offline flags."""
    from jaeger_ai.core.runtime import stack

    monkeypatch.setattr(stack, "operator_state_root", lambda: tmp_path)
    _write_instance_config(tmp_path, (
        "external_model:\n  provider: ollama\n  model: gemma-4-26b:latest\n  ctx: 32768\n"
    ))
    ollama, mcp = SERVICE_BY_ID["ollama"], SERVICE_BY_ID["mcp"]
    stack._launchd_dir()
    stack.plist_path_for(ollama).write_bytes(plistlib.dumps({"EnvironmentVariables": {
        "OLLAMA_CONTEXT_LENGTH": "16384", "OLLAMA_FLASH_ATTENTION": "1",
        "OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_KEEP_ALIVE": "30m",
        "OLLAMA_MAX_LOADED_MODELS": "3",
        "OLLAMA_HOST": "0.0.0.0:11434",           # never carried over
        "JAEGER_STATE_DIR": "/elsewhere",          # stack-owned
        "SOME_SECRET_TOKEN": "x",                  # not a tuning key
    }}))
    stack.plist_path_for(mcp).write_bytes(plistlib.dumps({"EnvironmentVariables": {
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    }}))

    for _ in range(2):  # the second sync reads the first sync's output
        stack.sync_plists(commit_sha="abc")
        o_env = plistlib.loads(stack.plist_path_for(ollama).read_bytes())["EnvironmentVariables"]
        m_env = plistlib.loads(stack.plist_path_for(mcp).read_bytes())["EnvironmentVariables"]
        assert o_env["OLLAMA_CONTEXT_LENGTH"] == "32768"  # instance ctx wins over stale plist
        assert o_env["OLLAMA_FLASH_ATTENTION"] == "1"
        assert o_env["OLLAMA_KV_CACHE_TYPE"] == "q8_0"
        assert o_env["OLLAMA_KEEP_ALIVE"] == "30m"
        assert o_env["OLLAMA_MAX_LOADED_MODELS"] == "3"
        assert o_env["OLLAMA_HOST"].startswith("127.0.0.1:")
        assert o_env["JAEGER_STATE_DIR"] == str(tmp_path)
        assert "SOME_SECRET_TOKEN" not in o_env
        assert m_env["HF_HUB_OFFLINE"] == "1"
        assert m_env["TRANSFORMERS_OFFLINE"] == "1"
        g_env = plistlib.loads(stack.plist_path_for(SERVICE_BY_ID["gateway"]).read_bytes())["EnvironmentVariables"]
        assert g_env["JAEGER_GATEWAY_OLLAMA_MODEL"] == "gemma-4-26b:latest"


def test_instance_stack_env_section_drives_plists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from jaeger_ai.core.runtime import stack

    monkeypatch.setattr(stack, "operator_state_root", lambda: tmp_path)
    _write_instance_config(tmp_path, (
        "external_model:\n  model: glm-5.3-flash:cloud\n  ctx: 1048576\n"
        "stack:\n  env:\n    all:\n      HF_HUB_OFFLINE: 1\n"
        "    ollama:\n      OLLAMA_CONTEXT_LENGTH: 8192\n      OLLAMA_HOST: 0.0.0.0:11434\n"
    ))
    o_env = plistlib.loads(build_plist(SERVICE_BY_ID["ollama"], commit_sha="abc").encode())["EnvironmentVariables"]
    g_env = plistlib.loads(build_plist(SERVICE_BY_ID["gateway"], commit_sha="abc").encode())["EnvironmentVariables"]
    assert o_env["OLLAMA_CONTEXT_LENGTH"] == "8192"   # cloud ctx is not pushed into Ollama
    assert o_env["OLLAMA_HOST"].startswith("127.0.0.1:")  # config cannot re-expose Ollama
    assert o_env["HF_HUB_OFFLINE"] == "1"
    assert g_env["HF_HUB_OFFLINE"] == "1"
    assert g_env["JAEGER_GATEWAY_HOST"] == "127.0.0.1"


def test_every_stack_plist_restarts_only_after_a_crash():
    for service in STACK_SERVICES:
        data = plistlib.loads(build_plist(service, commit_sha="abc").encode())
        assert data["KeepAlive"] == {"SuccessfulExit": False}, service.id


def test_installed_copy_writes_plists_for_the_source_checkout(tmp_path: Path, monkeypatch):
    """Run from site-packages, the stack must still launch the checkout.

    An installed wheel's ``__file__`` is site-packages: plists built from it
    had a site-packages WorkingDirectory/PYTHONPATH and a ``python -m``
    Web UI that crash-looped on ``No module named 'api'``."""
    import importlib

    from jaeger_ai.core.runtime import stack

    checkout = tmp_path / "JaegerAI"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "scripts" / "run-jaeger-webui.sh").write_text("#!/bin/zsh\n")
    monkeypatch.setenv("JAEGER_INSTALL_ROOT", str(checkout))
    try:
        stack = importlib.reload(stack)
        webui = plistlib.loads(build_plist_for(stack, "webui").encode())
        gateway = plistlib.loads(build_plist_for(stack, "gateway").encode())
        assert webui["ProgramArguments"] == ["/bin/zsh", str(checkout / "scripts" / "run-jaeger-webui.sh")]
        assert webui["WorkingDirectory"] == str(checkout)
        assert gateway["EnvironmentVariables"]["JAEGER_INSTALL_ROOT"] == str(checkout)
        assert gateway["EnvironmentVariables"]["PYTHONPATH"].split(":")[0] == str(checkout)
    finally:
        monkeypatch.delenv("JAEGER_INSTALL_ROOT")
        importlib.reload(stack)


def test_webui_without_its_launcher_fails_loudly(tmp_path: Path, monkeypatch):
    from jaeger_ai.core.runtime import stack

    monkeypatch.setattr(stack, "REPO_ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="JAEGER_INSTALL_ROOT"):
        build_plist(SERVICE_BY_ID["webui"], commit_sha="abc")


def build_plist_for(module, service_id: str) -> str:
    return module.build_plist(module.SERVICE_BY_ID[service_id], commit_sha="abc")


def test_gateway_lease_shutdown_exits_zero(monkeypatch):
    """A clean lease shutdown returns 0, so SuccessfulExit=false keeps it down."""
    import jaeger_ai.core.gateway.server as gateway_server

    async def leave(host, port):
        return None

    monkeypatch.setattr(gateway_server, "run_gateway_forever", leave)
    assert gateway_server.main(["--port", "0"]) == 0
