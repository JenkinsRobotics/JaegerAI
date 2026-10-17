"""Connect Apps: registry, read-only probes, owner-only confirmed install.

The installer is always mocked: no test runs ``code`` or touches argv.json or
~/.jaeger (paths are pointed at tmp via the gateway-side env overrides).
"""
from __future__ import annotations

import asyncio
import json
import subprocess

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.connect_apps import ConnectApps, load_registry, _strip_jsonc
from jaeger_ai.core.gateway.event_bus import EVENT_TYPES
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore

EXT = "jenkins-robotics.jaeger-chat"


class FakeCode:
    def __init__(self, installed: str | None = None, version: str = "1.142.0", rc: int = 0):
        self.installed, self.version, self.rc, self.calls = installed, version, rc, []

    def __call__(self, argv, **kw):
        assert kw.get("shell") is False and isinstance(argv, list)
        self.calls.append(argv)
        if argv[1] == "--list-extensions":
            out = f"{EXT}@{self.installed}\n" if self.installed else "other.ext@1.0.0\n"
            return subprocess.CompletedProcess(argv, 0, out, "")
        if argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, f"{self.version}\nabc\n", "")
        if argv[1] == "--install-extension":
            if self.rc == 0:
                self.installed = argv[2].rsplit("jaeger-chat-", 1)[1].removesuffix(".vsix")
            return subprocess.CompletedProcess(argv, self.rc, "", "boom" if self.rc else "")
        raise AssertionError(argv)


@pytest.fixture()
def env(tmp_path):
    code = tmp_path / "code"
    code.write_text("#!/bin/sh\nexit 1\n")
    code.chmod(0o755)
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "jaeger-chat-0.1.0.vsix").write_bytes(b"old")
    (apps / "jaeger-chat-0.2.0.vsix").write_bytes(b"new")
    argv = tmp_path / "argv.json"
    argv.write_text('{\n // comment\n "enable-proposed-api": ["%s"],\n}\n' % EXT)
    return {"JAEGER_CONNECT_APPS_CODE_CLI": str(code), "JAEGER_CONNECT_APPS_DIR": str(apps),
            "JAEGER_CONNECT_APPS_ARGV": str(argv)}


def test_registry_is_local_and_placeholders_have_no_actions():
    reg = load_registry()
    assert {a["id"] for a in reg["apps"]} >= {"vscode", "github", "gmail"}
    for app in reg["apps"]:
        assert not app["icon"].startswith("http")
        if app["status"] == "coming_soon":
            assert app["actions"] == []
    assert "connect_app.updated" in EVENT_TYPES


def test_jsonc_strip_keeps_strings():
    assert json.loads(_strip_jsonc('{"a": "x//y", /* c */ "b": [1,],}')) == {"a": "x//y", "b": [1]}


def test_probe_states(env, tmp_path):
    fake = FakeCode()
    apps = ConnectApps(runner=fake, environ=env)
    assert apps.state("vscode")["value"] == "not_installed"
    vsix = apps.find_vsix()
    assert (vsix["name"], vsix["version"]) == ("jaeger-chat-0.2.0.vsix", "0.2.0") and len(vsix["sha256"]) == 64
    assert apps.state("github")["value"] == "coming_soon"
    assert apps.state("nope") is None
    assert ConnectApps(runner=fake, environ={**env, "JAEGER_CONNECT_APPS_CODE_CLI": str(tmp_path / "x")}
                       ).state("vscode") == {"value": "needs_setup", "detail": "code_cli_missing",
                                             "checked_at": pytest.approx(0, abs=1e12)}
    assert ConnectApps(runner=fake, environ={**env, "JAEGER_CONNECT_APPS_DIR": str(tmp_path / "none")}
                       ).state("vscode")["detail"] == "apps_dir_missing"
    (tmp_path / "argv.json").write_text("{}")
    assert ConnectApps(runner=fake, environ=env).state("vscode")["detail"] == "argv_missing"
    assert ConnectApps(runner=FakeCode(installed="0.1.0"), environ=env).state("vscode") \
        | {"checked_at": 0} == {"value": "installed", "version": "0.1.0", "checked_at": 0,
                                 "vscode_version": "1.142.0"}
    assert not (tmp_path / "none").exists()  # probes never create directories


def test_vsix_symlink_out_of_dir_is_refused(env, tmp_path):
    outside = tmp_path / "evil.vsix"
    outside.write_bytes(b"x")
    apps_dir = tmp_path / "apps"
    for f in apps_dir.iterdir():
        f.unlink()
    (apps_dir / "jaeger-chat-9.9.9.vsix").symlink_to(outside)
    assert ConnectApps(runner=FakeCode(), environ=env).find_vsix() is None


def test_install_admission_and_idempotence(env):
    fake = FakeCode()
    apps = ConnectApps(runner=fake, environ=env)
    assert apps.begin_install("nope")[0] == 404
    assert apps.begin_install("github")[0] == 409
    status, body, plan = apps.begin_install("vscode")
    assert status == 202 and body["version"] == "0.2.0" and plan
    assert apps.begin_install("vscode")[0] == 409  # one at a time
    result = apps.run_install("vscode", plan, caller="webui")
    assert fake.calls[-3][1] == "--install-extension" or any(c[1] == "--install-extension" for c in fake.calls)
    install = [c for c in fake.calls if c[1] == "--install-extension"][0]
    assert install == [env["JAEGER_CONNECT_APPS_CODE_CLI"], "--install-extension", plan["vsix"]["path"]]
    assert result["state"]["value"] == "installed" and result["state"]["version"] == "0.2.0"
    assert result["audit"]["exit_code"] == 0 and result["audit"]["caller"] == "webui"
    status, body, plan = apps.begin_install("vscode")
    assert (status, body["changed"], plan) == (200, False, None)


def test_failed_install_is_error_with_redacted_stderr(env):
    apps = ConnectApps(runner=FakeCode(rc=1), environ=env)
    _, _, plan = apps.begin_install("vscode")
    result = apps.run_install("vscode", plan, caller="cli")
    assert result["state"]["value"] == "error" and result["state"]["detail"] == "boom"
    assert result["audit"]["exit_code"] == 1


@pytest.mark.asyncio
async def test_routes_owner_only_confirm_and_event(env, tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    gateway._connect_apps_service = ConnectApps(runner=FakeCode(), environ=env)
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        listing = await (await client.get("/v1/connect-apps")).json()
        assert listing["connected_count"] == 0 and listing["categories"]
        assert next(a for a in listing["apps"] if a["id"] == "vscode")["state"]["value"] == "not_installed"
        assert (await client.get("/v1/connect-apps/nope/state")).status == 404
        state = await (await client.get("/v1/connect-apps/vscode/state?refresh=1")).json()
        assert state["id"] == "vscode"
        assert (await client.post("/v1/connect-apps/vscode/install", json={})).status == 400
        assert (await client.post("/v1/connect-apps/github/install", json={"confirm": True})).status == 409
        resp = await client.post("/v1/connect-apps/vscode/install", json={"confirm": True})
        assert resp.status == 202 and (await resp.json())["state"] == "installing"
        await asyncio.wait_for(gateway._connect_install_task, 5)
        again = await client.post("/v1/connect-apps/vscode/install", json={"confirm": True})
        assert again.status == 200 and (await again.json())["changed"] is False
    for caller in ("ide", "jaegerd", "bridge"):
        async with TestClient(TestServer(gateway.app), headers=client_headers(caller)) as client:
            assert (await client.post("/v1/connect-apps/vscode/install", json={"confirm": True})).status == 403
    async with TestClient(TestServer(gateway.app), headers=client_headers("mcp")) as client:
        assert (await client.get("/v1/connect-apps")).status == 403
    events = [e for e in gateway.store.replay_events("*", 0)["events"] if e["event"] == "connect_app.updated"]
    assert [e["data"]["state"]["value"] for e in events] == ["installing", "installed"]
    assert events[-1]["data"]["audit"]["sha256"] and events[-1]["session_id"] == "*"
