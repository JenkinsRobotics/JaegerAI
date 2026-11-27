"""Hygiene & smoke tests for new-user CLI (`./jaeger`), stack CLI, installer (`./install.sh`), and `pyproject.toml`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]

STACK_SERVICE_REQUIRED_KEYS = {
    "id",
    "name",
    "label",
    "pid",
    "state",
    "raw_state",
    "ready",
    "managed",
    "configured",
    "port",
    "git_commit",
    "head_commit",
    "stale",
}


def test_cli_help_and_entrypoint_work() -> None:
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "jaeger_ai", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=False,
    )
    assert proc.returncode == 0
    assert "JaegerAI Operator CLI" in proc.stdout
    assert "./jaeger start" in proc.stdout
    assert "./jaeger stack" in proc.stdout
    assert "./jaeger stop" in proc.stdout
    assert "./jaeger restart" in proc.stdout
    assert "./jaeger app" in proc.stdout

    stack_help = subprocess.run(
        [sys.executable, "-B", "-m", "jaeger_ai", "stack", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=False,
    )
    assert stack_help.returncode == 0
    assert "status" in stack_help.stdout
    assert "up" in stack_help.stdout
    assert "down" in stack_help.stdout
    assert "restart" in stack_help.stdout


def test_stack_status_json_schema_and_companion_presence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from jaeger_ai import cli, stack

    launchd_dir = tmp_path / "state" / "launchd"
    launchd_dir.mkdir(parents=True)
    (launchd_dir / "com.jenkinsrobotics.jaeger-gateway.plist").write_text("<plist/>", encoding="utf-8")
    (launchd_dir / "com.jenkinsrobotics.jaeger-voice.plist").write_text("<plist/>", encoding="utf-8")
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(stack, "_launch_agents_dir", lambda: tmp_path / "empty_agents")
    monkeypatch.setattr(stack, "_current_git_commit", lambda: "abcdef1234567890")

    def fake_launchctl(args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        target = args[1] if len(args) > 1 else ""
        if args[:1] == ["print"] and target.endswith("/com.jenkinsrobotics.jaeger-gateway"):
            return subprocess.CompletedProcess(
                args=["launchctl", *args],
                returncode=0,
                stdout=(
                    "gui/501/com.jenkinsrobotics.jaeger-gateway = {\n"
                    "\tstate = running\n"
                    "\tpid = 4242\n"
                    "\tJAEGER_GIT_COMMIT => abcdef1234567890\n"
                    "}\n"
                ),
                stderr="",
            )
        if args[:1] == ["print"] and target.endswith("/com.jenkinsrobotics.jaeger-voice"):
            return subprocess.CompletedProcess(
                args=["launchctl", *args],
                returncode=0,
                stdout="gui/501/com.jenkinsrobotics.jaeger-voice = {\n\tstate = running\n\tpid = 5151\n}\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=["launchctl", *args], returncode=113, stdout="", stderr="not found")

    def fake_probe(url: str, *, timeout: float = 1.5, accept_4xx: bool = False) -> tuple[bool, dict[str, Any] | None]:
        if url.endswith(":33418/health") or url.endswith(":8790/health"):
            return True, {"ok": True, "pid": 4242}
        if url.endswith(":8794/health"):
            return True, {"ok": True}
        return False, None

    monkeypatch.setattr(stack, "_launchctl", fake_launchctl)
    monkeypatch.setattr(stack, "_probe_http", fake_probe)

    rc = cli.main(["stack", "status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    services = payload["services"]
    assert [s["id"] for s in services] == ["gateway", "voice"]

    for svc in services:
        assert STACK_SERVICE_REQUIRED_KEYS.issubset(svc.keys())
        assert isinstance(svc["id"], str)
        assert isinstance(svc["name"], str)
        assert isinstance(svc["label"], str)
        assert isinstance(svc["state"], str)
        assert isinstance(svc["ready"], bool)
        assert isinstance(svc["managed"], bool)
        assert isinstance(svc["configured"], bool)
        assert isinstance(svc["stale"], bool)

    gw = services[0]
    assert gw["label"] == "com.jenkinsrobotics.jaeger-gateway"
    assert gw["pid"] == 4242
    assert gw["state"] == "Ready"
    assert gw["raw_state"] == "running"
    assert gw["ready"] is True
    assert gw["managed"] is True
    assert gw["configured"] is True
    assert gw["port"] == 33418
    assert gw["webui_port"] == 8790
    assert gw["webui_ready"] is True
    assert gw["git_commit"] == "abcdef1234567890"
    assert gw["head_commit"] == "abcdef1234567890"
    assert gw["stale"] is False


def test_stack_aliases_unknown_and_idempotent_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from jaeger_ai import cli, stack

    launchd_dir = tmp_path / "state" / "launchd"
    launchd_dir.mkdir(parents=True)
    (launchd_dir / "com.jenkinsrobotics.jaeger-gateway.plist").write_text("<plist/>", encoding="utf-8")
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(stack, "_launch_agents_dir", lambda: tmp_path / "empty_agents")
    monkeypatch.setattr(stack, "_current_git_commit", lambda: "11112222")

    # Alias deduplication + unknown ignoring
    targets, aliases, ignored = stack.resolve_service_targets(["gateway", "agent", "webui", "mcp", "nonexistent"])
    assert [t.id for t in targets] == ["gateway", "mcp"]
    assert aliases == {"agent": "gateway", "webui": "gateway"}
    assert ignored == ["nonexistent"]

    # Idempotent `stack up gateway agent webui mcp bogus --json`:
    # Gateway is already live and healthy; mcp is unmanaged; bogus is unknown.
    # Must NOT bootout/bootstrap/kickstart Gateway and MUST return ok=True.
    launchctl_calls: list[list[str]] = []

    def fake_launchctl(args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        launchctl_calls.append(list(args))
        if args[:1] == ["print"] and args[1].endswith("/com.jenkinsrobotics.jaeger-gateway"):
            return subprocess.CompletedProcess(
                args=["launchctl", *args],
                returncode=0,
                stdout="state = running\npid = 9001\nJAEGER_GIT_COMMIT => 11112222\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=["launchctl", *args], returncode=113, stdout="", stderr="not found")

    def fake_probe(url: str, *, timeout: float = 1.5, accept_4xx: bool = False) -> tuple[bool, dict[str, Any] | None]:
        if url.endswith(":33418/health") or url.endswith(":8790/health"):
            return True, {"ok": True, "pid": 9001}
        return False, None

    monkeypatch.setattr(stack, "_launchctl", fake_launchctl)
    monkeypatch.setattr(stack, "_probe_http", fake_probe)

    rc = cli.main(["stack", "up", "gateway", "agent", "webui", "mcp", "bogus", "--json"])
    assert rc == 0
    reply = json.loads(capsys.readouterr().out)
    assert reply["ok"] is True
    assert reply["step"] == "done"
    assert reply["error"] is None
    assert reply["aliases"] == {"agent": "gateway", "webui": "gateway"}
    assert reply["ignored"] == ["bogus"]
    assert reply["skipped_unmanaged"] == ["mcp"]
    assert [s["id"] for s in reply["services"]] == ["gateway", "mcp"]
    assert reply["services"][0]["ready"] is True
    # Only read-only `print` calls — zero mutations on a live healthy Gateway!
    assert all(call[0] == "print" for call in launchctl_calls)


def test_stack_up_down_restart_and_app_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from jaeger_ai import cli, stack

    launchd_dir = tmp_path / "state" / "launchd"
    launchd_dir.mkdir(parents=True)
    (launchd_dir / "com.jenkinsrobotics.jaeger-gateway.plist").write_text("<plist/>", encoding="utf-8")
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(stack, "_launch_agents_dir", lambda: tmp_path / "empty_agents")
    monkeypatch.setattr(stack, "_current_git_commit", lambda: "deadbeef")

    running = {"gateway": False}
    ops: list[str] = []

    def fake_launchctl(args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        verb = args[0]
        ops.append(verb)
        if verb == "print":
            if running["gateway"] and args[1].endswith("/com.jenkinsrobotics.jaeger-gateway"):
                return subprocess.CompletedProcess(
                    args=["launchctl", *args],
                    returncode=0,
                    stdout="state = running\npid = 7777\nJAEGER_GIT_COMMIT => deadbeef\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=113, stdout="", stderr="not loaded")
        if verb == "bootstrap":
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")
        if verb == "kickstart":
            running["gateway"] = True
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")
        if verb == "bootout":
            running["gateway"] = False
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")

    def fake_probe(url: str, *, timeout: float = 1.5, accept_4xx: bool = False) -> tuple[bool, dict[str, Any] | None]:
        if running["gateway"] and (url.endswith(":33418/health") or url.endswith(":8790/health")):
            return True, {"ok": True, "pid": 7777}
        return False, None

    monkeypatch.setattr(stack, "_launchctl", fake_launchctl)
    monkeypatch.setattr(stack, "_probe_http", fake_probe)
    monkeypatch.setattr(stack, "_pid_alive", lambda _pid: False)

    # 1. Cold `stack up --json` bootstraps & kickstarts Gateway
    assert cli.main(["stack", "up", "--json", "--wait", "2"]) == 0
    up_reply = json.loads(capsys.readouterr().out)
    assert up_reply["ok"] is True
    assert up_reply["services"][0]["ready"] is True
    assert "bootstrap" in ops and "kickstart" in ops

    # 2. `./jaeger restart --json` cleanly reloads & restarts Gateway
    ops.clear()
    assert cli.main(["restart", "--json", "--wait", "2"]) == 0
    restart_reply = json.loads(capsys.readouterr().out)
    assert restart_reply["ok"] is True
    assert restart_reply["services"][0]["ready"] is True
    assert "bootout" in ops and "bootstrap" in ops and "kickstart" in ops

    # 3. `./jaeger stop --json` boots out Gateway
    ops.clear()
    assert cli.main(["stop", "--json", "--wait", "1"]) == 0
    down_reply = json.loads(capsys.readouterr().out)
    assert down_reply["ok"] is True
    assert down_reply["services"][0]["ready"] is False
    assert "bootout" in ops

    # 4. `./jaeger app` returns exit 1 cleanly if app path is missing
    monkeypatch.setenv("JAEGER_APP_PATH", str(tmp_path / "MissingJaegerAI.app"))
    assert cli.main(["app"]) == 1
    assert "not found" in capsys.readouterr().err


def test_setup_dry_run_and_pyproject_workspace_sync() -> None:
    proc = subprocess.run(
        ["bash", str(REPO / "scripts/setup.sh"), "--profile", "full", "--dry-run"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=False,
    )
    assert proc.returncode == 0
    assert "jaeger-droid" in proc.stdout

    pyproj = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert '"packages/jaeger-ui-avatar"' in pyproj
    assert "jaeger-droid = { workspace = true }" in pyproj
    assert "jaeger-cognition = { workspace = true }" in pyproj


def test_runtime_registers_embodiment_and_studio_tools(tmp_path: Path) -> None:
    from jaeger_gateway import ModularGatewayRuntime

    rt = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    try:
        # Must appear under DEFAULT list_tools() limit (no silent truncation!)
        names = {t["name"] for t in rt.tools.list_tools()}
        for expected in (
            "droid_devices",
            "droid_act",
            "droid_capture",
            "avatar_express",
            "minecraft_status",
            "minecraft_act",
            "jp01_act",
            "youtube_studio",
            "media_archive",
            "business_team",
            "persistent_goals",
        ):
            assert expected in names, f"missing platform tool: {expected}"

        # Execute each core platform tool directly to guarantee ToolResult(tool_name=...) works
        assert rt.tools.execute("droid_devices", {"refresh": False}).ok is True
        assert rt.tools.execute("avatar_express", {"emotion": "happy", "state": "speaking"}).ok is True
        assert rt.tools.execute("minecraft_status", {}).ok is True
        assert rt.tools.execute("business_team", {}).ok is True
    finally:
        rt.close()


def test_stack_restart_waits_for_bootout_and_retries_transient_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from jaeger_ai import stack

    launchd_dir = tmp_path / "state" / "launchd"
    launchd_dir.mkdir(parents=True)
    (launchd_dir / "com.jenkinsrobotics.jaeger-gateway.plist").write_text("<plist/>", encoding="utf-8")
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(stack, "_launch_agents_dir", lambda: tmp_path / "empty_agents")
    monkeypatch.setattr(stack, "_current_git_commit", lambda: "cafebabe")

    sleeps: list[float] = []
    monkeypatch.setattr(stack.time, "sleep", lambda s: sleeps.append(float(s)))

    # Simulate macOS launchd async bootout:
    # - Initial print -> loaded (0)
    # - bootout -> starts async teardown; next 2 prints STILL return 0, then 113 (unloaded)
    # - bootstrap attempt 1 -> exit 5 (EIO), attempt 2 -> exit 37 (EINPROGRESS), attempt 3 -> 0
    # - kickstart -k -> 0 and service becomes running + HTTP ready
    state = {
        "phase": "initial_loaded",
        "unloading_prints_left": 2,
        "bootstrap_errors": [5, 37],
        "running": False,
    }
    calls: list[list[str]] = []

    def fake_launchctl(args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        verb = args[0]
        if verb == "print":
            if state["phase"] == "initial_loaded":
                return subprocess.CompletedProcess(
                    args=["launchctl", *args],
                    returncode=0,
                    stdout="state = running\npid = 1234\nJAEGER_GIT_COMMIT => cafebabe\n",
                    stderr="",
                )
            if state["phase"] == "unloading":
                if state["unloading_prints_left"] > 0:
                    state["unloading_prints_left"] -= 1
                    return subprocess.CompletedProcess(
                        args=["launchctl", *args],
                        returncode=0,
                        stdout="state = running\npid = 1234\n",
                        stderr="",
                    )
                state["phase"] = "unloaded"
                return subprocess.CompletedProcess(
                    args=["launchctl", *args], returncode=113, stdout="", stderr="not loaded"
                )
            if state["phase"] in ("bootstrapped", "running"):
                return subprocess.CompletedProcess(
                    args=["launchctl", *args],
                    returncode=0,
                    stdout="state = running\npid = 5678\nJAEGER_GIT_COMMIT => cafebabe\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=["launchctl", *args], returncode=113, stdout="", stderr="not loaded"
            )
        if verb == "bootout":
            state["phase"] = "unloading"
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")
        if verb == "bootstrap":
            assert state["phase"] == "unloaded", f"bootstrap called before unload finished: {state['phase']}"
            if state["bootstrap_errors"]:
                code = state["bootstrap_errors"].pop(0)
                return subprocess.CompletedProcess(
                    args=["launchctl", *args],
                    returncode=code,
                    stdout="",
                    stderr=f"Bootstrap failed: {code}: transient launchd race",
                )
            state["phase"] = "bootstrapped"
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")
        if verb == "kickstart":
            assert state["phase"] == "bootstrapped"
            state["phase"] = "running"
            state["running"] = True
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")

    def fake_probe(url: str, *, timeout: float = 1.5, accept_4xx: bool = False) -> tuple[bool, dict[str, Any] | None]:
        if state["running"] and (url.endswith(":33418/health") or url.endswith(":8790/health")):
            return True, {"ok": True, "pid": 5678}
        return False, None

    monkeypatch.setattr(stack, "_launchctl", fake_launchctl)
    monkeypatch.setattr(stack, "_probe_http", fake_probe)

    reply = stack.stack_restart(["gateway"], wait_timeout=2.0)
    assert reply["ok"] is True
    assert reply["step"] == "done"
    assert reply["error"] is None
    assert reply["services"][0]["ready"] is True
    assert reply["services"][0]["pid"] == 5678

    verbs = [c[0] for c in calls]
    bootout_idx = verbs.index("bootout")
    first_bootstrap_idx = verbs.index("bootstrap")
    kickstart_idx = verbs.index("kickstart")
    # Must poll `print` after bootout until unloaded before first bootstrap
    assert verbs[bootout_idx + 1 : first_bootstrap_idx] == ["print", "print", "print"]
    # Must retry bootstrap across exit codes 5 and 37 before succeeding on 3rd try
    assert verbs.count("bootstrap") == 3
    assert first_bootstrap_idx < kickstart_idx
    assert sleeps.count(stack.LAUNCHCTL_POLL_INTERVAL) >= 4


def test_stack_restart_recovers_if_kickstart_hits_late_unload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from jaeger_ai import stack

    launchd_dir = tmp_path / "state" / "launchd"
    launchd_dir.mkdir(parents=True)
    (launchd_dir / "com.jenkinsrobotics.jaeger-gateway.plist").write_text("<plist/>", encoding="utf-8")
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(stack, "_launch_agents_dir", lambda: tmp_path / "empty_agents")
    monkeypatch.setattr(stack, "_current_git_commit", lambda: "cafebabe")
    monkeypatch.setattr(stack, "BOOTOUT_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(stack.time, "sleep", lambda _s: None)

    # Bootout poll times out immediately while still reporting loaded, then job unloads
    # right before kickstart -> recovery path bootstraps and kickstarts cleanly.
    state = {"loaded": True, "kick_failed_once": False, "running": False}
    verbs: list[str] = []

    def fake_launchctl(args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        verb = args[0]
        verbs.append(verb)
        if verb == "print":
            if state["loaded"]:
                return subprocess.CompletedProcess(
                    args=["launchctl", *args],
                    returncode=0,
                    stdout="state = running\npid = 9999\nJAEGER_GIT_COMMIT => cafebabe\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=113, stdout="", stderr="not loaded")
        if verb == "bootout":
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")
        if verb == "kickstart":
            if not state["kick_failed_once"]:
                state["kick_failed_once"] = True
                state["loaded"] = False
                return subprocess.CompletedProcess(
                    args=["launchctl", *args], returncode=113, stdout="", stderr="Could not find service"
                )
            state["running"] = True
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")
        if verb == "bootstrap":
            state["loaded"] = True
            return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=["launchctl", *args], returncode=0, stdout="", stderr="")

    def fake_probe(url: str, *, timeout: float = 1.5, accept_4xx: bool = False) -> tuple[bool, dict[str, Any] | None]:
        if state["running"] and (url.endswith(":33418/health") or url.endswith(":8790/health")):
            return True, {"ok": True, "pid": 9999}
        return False, None

    monkeypatch.setattr(stack, "_launchctl", fake_launchctl)
    monkeypatch.setattr(stack, "_probe_http", fake_probe)

    reply = stack.stack_restart(["gateway"], wait_timeout=2.0)
    assert reply["ok"] is True
    assert verbs.count("kickstart") == 2
    assert verbs.count("bootstrap") == 1


def test_install_droid_deck_keys_generates_all_six_applets_and_enforces_safety(
    tmp_path: Path,
) -> None:
    import http.server
    import os
    import plistlib
    import threading

    script_path = REPO / "scripts" / "install-droid-deck-keys.py"
    assert script_path.is_file()

    # In-process stub Gateway for end-to-end execution checks of the generated shell runners.
    gw_state: dict[str, Any] = {
        "estop_active": False,
        "sleeping": False,
        "fail_sleep": False,
        "calls": [],
    }

    class _StubHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            gw_state["calls"].append(("GET", self.path, None))
            if self.path == "/health":
                self._send_json(200, {"ok": True})
                return
            if self.path == "/v1/system/resources":
                self._send_json(200, {"ok": True, "resources": {"estop_active": gw_state["estop_active"]}})
                return
            if self.path == "/v1/droid/status":
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "awake": not gw_state["sleeping"],
                        "sleeping": gw_state["sleeping"],
                        "estop_active": gw_state["estop_active"],
                        "vision": None,
                    },
                )
                return
            self._send_json(404, {"ok": False})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            body_raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(body_raw.decode("utf-8")) if body_raw else {}
            gw_state["calls"].append(("POST", self.path, body))
            if self.path == "/v1/droid/wake":
                if gw_state["estop_active"]:
                    self._send_json(409, {"ok": False, "error": "estop_active"})
                    return
                gw_state["sleeping"] = False
                self._send_json(200, {"ok": True, "action": "wake", "sleeping": False})
                return
            if self.path == "/v1/droid/sleep":
                if gw_state["fail_sleep"]:
                    self._send_json(503, {"ok": False, "error": "gateway_sleep_unavailable"})
                    return
                gw_state["sleeping"] = True
                self._send_json(200, {"ok": True, "action": "sleep", "sleeping": True})
                return
            if self.path == "/v1/embodiment/droid/act":
                if gw_state["estop_active"] or gw_state["sleeping"]:
                    self._send_json(409, {"ok": False, "error": "blocked"})
                    return
                self._send_json(200, {"ok": True, "action": body.get("action"), "params": body.get("params")})
                return
            self._send_json(404, {"ok": False})

    server: http.server.ThreadingHTTPServer | None = None
    server_thread: threading.Thread | None = None
    gateway_url = "http://127.0.0.1:33418"
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        port = server.server_address[1]
        gateway_url = f"http://127.0.0.1:{port}"
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
    except PermissionError:
        server = None

    try:
        state_dir = tmp_path / "state"
        # 1. Dry-run --applets-only writes nothing
        dry = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script_path),
                "--applets-only",
                "--state-dir",
                str(state_dir),
                "--gateway",
                gateway_url,
            ],
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
        assert dry.returncode == 0, dry.stderr
        assert not (state_dir / "droid/controls").exists()

        # 2. Full manifest + applets --apply run
        droid_page_dir = tmp_path / "profiles" / "DROID_UUID"
        jaeger_page_dir = tmp_path / "profiles" / "JAEGER_UUID"
        droid_page_dir.mkdir(parents=True)
        jaeger_page_dir.mkdir(parents=True)

        def _make_manifest(name: str, bundle_id: str) -> dict[str, Any]:
            return {
                "Name": name,
                "Controllers": [
                    {
                        "Type": "Keypad",
                        "Actions": {
                            "0,0": {
                                "ActionID": "orig-id",
                                "Settings": {"bundle_id": bundle_id},
                                "States": [{"Title": "WAKE\nDROID"}],
                            }
                        },
                    }
                ],
            }

        droid_manifest = droid_page_dir / "manifest.json"
        jaeger_manifest = jaeger_page_dir / "manifest.json"
        droid_manifest.write_text(json.dumps(_make_manifest("DROID", "com.jenkinsrobotics.droid.toggle")), encoding="utf-8")
        jaeger_manifest.write_text(json.dumps(_make_manifest("JAEGER", "com.jenkinsrobotics.droid.droid")), encoding="utf-8")

        apply_proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script_path),
                "--state-dir",
                str(state_dir),
                "--gateway",
                gateway_url,
                "--page",
                str(droid_manifest),
                "--wake-page",
                str(jaeger_manifest),
                "--apply",
            ],
            capture_output=True,
            text=True,
            timeout=20.0,
            check=False,
        )
        assert apply_proc.returncode == 0, apply_proc.stderr

        # Verify manifest updates (Wake bound on both pages, Sleep added at 4,0 on DROID)
        updated_droid = json.loads(droid_manifest.read_text(encoding="utf-8"))
        updated_actions = updated_droid["Controllers"][0]["Actions"]
        assert updated_actions["0,0"]["Settings"]["bundle_id"] == "com.jenkinsrobotics.droid.wake"
        assert updated_actions["4,0"]["Settings"]["bundle_id"] == "com.jenkinsrobotics.droid.sleep"
        updated_jaeger = json.loads(jaeger_manifest.read_text(encoding="utf-8"))
        assert updated_jaeger["Controllers"][0]["Actions"]["0,0"]["Settings"]["bundle_id"] == "com.jenkinsrobotics.droid.wake"

        # 3. Verify all 6 .app bundles exist, are executable, pass `sh -n`, and drop dead control.sock
        expected_actions = ("wake", "sleep", "droid", "stop", "look", "mute")
        runners: dict[str, Path] = {}
        for action in expected_actions:
            app = state_dir / "droid/controls" / f"Jaeger-{action}.app"
            info_path = app / "Contents/Info.plist"
            runner = app / "Contents/MacOS/runner"
            assert info_path.is_file(), f"Missing Info.plist for {action}"
            assert runner.is_file(), f"Missing runner for {action}"
            assert os.access(runner, os.X_OK), f"Runner not executable for {action}"

            plist = plistlib.loads(info_path.read_bytes())
            assert plist["CFBundleIdentifier"] == f"com.jenkinsrobotics.droid.{action}"
            assert plist["CFBundleExecutable"] == "runner"
            assert plist["LSUIElement"] is True

            src = runner.read_text(encoding="utf-8")
            assert "/control.sock" not in src and "http://droid/" not in src, f"Legacy socket left in {action}"

            syntax = subprocess.run(["/bin/sh", "-n", str(runner)], capture_output=True, text=True, check=False)
            assert syntax.returncode == 0, f"sh -n failed for {action}: {syntax.stderr}"
            runners[action] = runner

        # Also verify --applets-only --apply refreshes all 6 without needing --page,
        # and verify offline fail-closed / fail-safe fallback behavior unconditionally.
        only_state = tmp_path / "only_state"
        only_proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script_path),
                "--applets-only",
                "--apply",
                "--state-dir",
                str(only_state),
                "--gateway",
                "http://127.0.0.1:1",
            ],
            capture_output=True,
            text=True,
            timeout=20.0,
            check=False,
        )
        assert only_proc.returncode == 0, only_proc.stderr
        offline_ptz_log = tmp_path / "offline_ptz.log"
        offline_ptz = only_state / "droid/bin/droid-ptz"
        offline_ptz.parent.mkdir(parents=True, exist_ok=True)
        offline_ptz.write_text(f'#!/bin/sh\necho "$@" >> "{offline_ptz_log}"\n', encoding="utf-8")
        offline_ptz.chmod(0o755)
        for action in expected_actions:
            assert (only_state / "droid/controls" / f"Jaeger-{action}.app/Contents/MacOS/runner").is_file()
        assert subprocess.run([str(only_state / "droid/controls/Jaeger-wake.app/Contents/MacOS/runner")], check=False).returncode != 0
        assert subprocess.run([str(only_state / "droid/controls/Jaeger-look.app/Contents/MacOS/runner")], check=False).returncode != 0
        assert subprocess.run([str(only_state / "droid/controls/Jaeger-droid.app/Contents/MacOS/runner")], check=False).returncode != 0
        assert subprocess.run([str(only_state / "droid/controls/Jaeger-sleep.app/Contents/MacOS/runner")], check=False).returncode == 0
        assert subprocess.run([str(only_state / "droid/controls/Jaeger-stop.app/Contents/MacOS/runner")], check=False).returncode == 0
        assert subprocess.run([str(only_state / "droid/controls/Jaeger-mute.app/Contents/MacOS/runner")], check=False).returncode == 0
        assert offline_ptz_log.read_text(encoding="utf-8").strip().splitlines() == [
            "abs 0 -306000",
            "abs 0 -306000",
        ]

        # 4. Execute runners end-to-end against stub Gateway when loopback curl is permitted
        loopback_curl_ok = False
        if server is not None:
            probe = subprocess.run(
                ["/usr/bin/curl", "-fsS", "--max-time", "2", f"{gateway_url}/health"],
                capture_output=True,
                check=False,
            )
            loopback_curl_ok = probe.returncode == 0

        if loopback_curl_ok:
            env = {**os.environ, "JAEGER_DROID_LOOK_PAUSE": "0.01"}

            # Install fake droid-ptz to verify direct fallback when Gateway sleep fails
            ptz_log = tmp_path / "ptz.log"
            ptz_bin = state_dir / "droid/bin/droid-ptz"
            ptz_bin.parent.mkdir(parents=True, exist_ok=True)
            ptz_bin.write_text(f'#!/bin/sh\necho "$@" >> "{ptz_log}"\n', encoding="utf-8")
            ptz_bin.chmod(0o755)

            # Wake blocked fail-closed under E-Stop
            gw_state["estop_active"] = True
            gw_state["sleeping"] = True
            gw_state["calls"].clear()
            assert subprocess.run([str(runners["wake"])], env=env, check=False).returncode != 0
            assert not any(p == "/v1/droid/wake" for _, p, _ in gw_state["calls"])

            # Look blocked fail-closed under E-Stop
            gw_state["calls"].clear()
            assert subprocess.run([str(runners["look"])], env=env, check=False).returncode != 0
            assert not any(p == "/v1/embodiment/droid/act" for _, p, _ in gw_state["calls"])

            # Sleep & Stop ALWAYS succeed under E-Stop (fail-safe privacy!)
            gw_state["sleeping"] = False
            gw_state["calls"].clear()
            assert subprocess.run([str(runners["sleep"])], env=env, check=False).returncode == 0
            assert gw_state["sleeping"] is True
            assert any(m == "POST" and p == "/v1/droid/sleep" for m, p, _ in gw_state["calls"])

            gw_state["sleeping"] = False
            gw_state["calls"].clear()
            assert subprocess.run([str(runners["stop"])], env=env, check=False).returncode == 0
            assert gw_state["sleeping"] is True
            assert any(
                m == "POST" and p == "/v1/droid/sleep" and (b or {}).get("reason") == "stream_deck_stop"
                for m, p, b in gw_state["calls"]
            )

            # Sleep fallback to direct `droid-ptz abs 0 -306000` when Gateway sleep errors
            gw_state["fail_sleep"] = True
            assert subprocess.run([str(runners["sleep"])], env=env, check=False).returncode == 0
            assert "abs 0 -306000" in ptz_log.read_text(encoding="utf-8")
            gw_state["fail_sleep"] = False

            # Legacy toggle (`Jaeger-droid.app`): awake under E-Stop -> sleeps (fail-safe!)
            gw_state["estop_active"] = True
            gw_state["sleeping"] = False
            assert subprocess.run([str(runners["droid"])], env=env, check=False).returncode == 0
            assert gw_state["sleeping"] is True

            # Legacy toggle: asleep under E-Stop -> blocked by wake E-Stop gate!
            assert subprocess.run([str(runners["droid"])], env=env, check=False).returncode != 0
            assert gw_state["sleeping"] is True

            # Release E-Stop -> Wake succeeds, Look wakes-if-sleeping and sweeps left/right/center
            gw_state["estop_active"] = False
            gw_state["sleeping"] = True
            assert subprocess.run([str(runners["droid"])], env=env, check=False).returncode == 0
            assert gw_state["sleeping"] is False

            gw_state["sleeping"] = True
            gw_state["calls"].clear()
            assert subprocess.run([str(runners["look"])], env=env, check=False).returncode == 0
            assert gw_state["sleeping"] is False
            act_bodies = [b for m, p, b in gw_state["calls"] if m == "POST" and p == "/v1/embodiment/droid/act"]
            assert act_bodies == [
                {"action": "look_at", "params": {"pan_deg": -35, "tilt_deg": 0}},
                {"action": "look_at", "params": {"pan_deg": 35, "tilt_deg": 0}},
                {"action": "center", "params": {}},
            ]

            # Mute exits 0 cleanly and logs without hanging
            assert subprocess.run([str(runners["mute"])], env=env, check=False).returncode == 0
            log_text = (state_dir / "logs/droid-controls.log").read_text(encoding="utf-8")
            assert "Droid mute" in log_text
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=2.0)
