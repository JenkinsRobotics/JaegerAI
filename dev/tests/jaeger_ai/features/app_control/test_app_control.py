"""AppControl: every adapter with a fake host. Never touches a real app, plist or config."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.features.app_control import configfile as cf
from jaeger_ai.features.app_control.adapters import AppSpec, ConfigSpec, Host, default_specs
from jaeger_ai.features.app_control.service import AppControl, AppControlError


def ok(stdout=""):
    return subprocess.CompletedProcess([], 0, stdout, "")


class FakeHost(Host):
    """Records commands; simulates pgrep/launchctl/open/osascript. No real process is run."""

    def __init__(self, running=(), installed=None):
        self.calls: list[list[str]] = []
        self.running = set(running)
        self.unloaded: set[str] = set()
        self.installed_ids = installed
        super().__init__(runner=self.fake_run, which=lambda b: f"/fake/bin/{b}", uid=501)

    def fake_run(self, argv, timeout=30, input=None):
        self.calls.append(list(argv))
        if argv[0] == "pgrep":
            return ok() if any(f"/{a}.app/" in argv[2] or argv[2].startswith(a) for a in self.running) else subprocess.CompletedProcess(argv, 1, "", "")
        if argv[:2] == ["launchctl", "print"]:
            label = argv[2].split("/")[-1]
            if label in self.unloaded:
                return subprocess.CompletedProcess(argv, 113, "", "not found")
            if label in self.running:
                return ok("state = running\n\tpid = 4242\n")
            return ok("state = waiting\n")
        if argv[0] == "osascript":
            for r in list(self.running):
                self.running.discard(r)
            return ok()
        if argv[:2] == ["launchctl", "bootout"]:
            self.running.discard(argv[2].split("/")[-1])
            self.unloaded.add(argv[2].split("/")[-1])
        return ok("fake output")

    def installed(self, spec):
        return self.installed_ids is None or spec.id in self.installed_ids

    def app_running(self, spec):
        if spec.kind == "macapp":
            return spec.id in self.running
        return super().app_running(spec)


def _ctl(tmp_path, specs, host=None, events=None):
    ev = events if events is not None else []
    return AppControl(host=host or FakeHost(), specs=specs, root=tmp_path / "state",
                      publish=lambda k, d: ev.append((k, d)), sleep=lambda s: None)


def mac(id="demo", cfg=None, **kw):
    return AppSpec(id, id.title(), "macapp", bundle_id=f"com.example.{id}", app_path=Path(f"/Applications/{id}.app"),
                   configs=cfg or (), **kw)


# ── configfile ──

def test_redaction_hides_secrets_everywhere():
    data = {"mcpServers": {"j": {"url": "http://127.0.0.1:8792/mcp", "headers": {"Authorization": "Bearer abcdefghijklmnop"},
                                 "env": {"X": "plain"}, "api_key": "k", "args": ["--token", "sk-abcdefghijkl"]}},
            "model": "gpt", "nested": {"github_token": {"a": 1}}, "note": "uses Bearer abcdefghijklmnop123"}
    r = cf.redact(data)
    s = json.dumps(r)
    for secret in ("abcdefghijklmnop", "sk-abc", "plain", '"k"'):
        assert secret not in s
    assert r["mcpServers"]["j"]["url"] == "http://127.0.0.1:8792/mcp" and r["model"] == "gpt"
    assert r["nested"]["github_token"]["a"] == cf.REDACTED


def test_allow_list_and_ops():
    allow = ("mcpServers.*", "model")
    assert cf.allowed("mcpServers.x", allow) and cf.allowed("mcpServers.x.url", allow) and cf.allowed("model", allow)
    assert not cf.allowed("mcpServers", allow) and not cf.allowed("permissions.allow", allow) and not cf.allowed("modelx", allow)
    new = cf.apply_ops({"a": 1}, [{"op": "set", "path": "mcpServers.j", "value": {"url": "u"}}], allow)
    assert new == {"a": 1, "mcpServers": {"j": {"url": "u"}}}
    assert cf.apply_ops(new, [{"op": "delete", "path": "mcpServers.j"}], allow) == {"a": 1, "mcpServers": {}}
    with pytest.raises(cf.ConfigError):
        cf.apply_ops({}, [{"op": "set", "path": "permissions.allow", "value": 1}], allow)


def test_formats_roundtrip_and_jsonc_comment_guard():
    assert cf.parse("jsonc", b'{"a": 1, // c\n "b": "x//y", /* z */ }') == {"a": 1, "b": "x//y"}
    with pytest.raises(cf.ConfigError):
        cf.dump("jsonc", {"a": 1}, b'{"a": 1 // keep me\n}')
    assert cf.parse("jsonc", cf.dump("jsonc", {"a": 1}, b'{"a": 0}')) == {"a": 1}
    t = cf.dump("toml", {"mcp_servers": {"j": {"url": "u"}}})
    assert cf.parse("toml", t)["mcp_servers"]["j"]["url"] == "u"
    assert cf.parse("plist", cf.dump("plist", {"k": "v"})) == {"k": "v"}
    with pytest.raises(cf.ConfigError):
        cf.parse("json", b"{nope")


# ── registry: every surveyed app has an adapter ──

def test_default_registry_covers_every_app():
    ids = {s.id for s in default_specs()}
    for a in ("muse", "codex_app", "codex_cli", "claude_desktop", "claude_code", "gemini_desktop", "gemini_cli", "copilot",
              "opencode", "antigravity", "antigravity_ide", "cursor", "vscode", "homeclaw", "cuadriver", "sam", "openclaw",
              "ollama", "obsidian", "n8n", "jaeger-gateway", "jaeger-webui", "jaeger-mcp-http", "jaeger-jobs", "jaeger-ares-worker"):
        assert a in ids, a
    specs = {s.id: s for s in default_specs()}
    assert specs["jaeger-gateway"].actions == ["restart"]
    assert "invoke:exec" in specs["codex_cli"].actions and "invoke:prompt" in specs["gemini_cli"].actions
    assert specs["claude_code"].configs[0].vendor_cli == "claude"
    assert specs["claude_desktop"].configs[0].rewritten_by_app
    assert not specs["muse"].configs and not specs["gemini_desktop"].configs


def test_obsidian_status_only_and_vault_state(tmp_path, monkeypatch):
    spec = next(s for s in default_specs() if s.id == "obsidian")
    host = FakeHost(installed={"obsidian"}, running={"obsidian"})
    ctl = _ctl(tmp_path, [spec], host)
    monkeypatch.delenv("JAEGER_OBSIDIAN_VAULT", raising=False)
    disabled = ctl.app_status("obsidian")
    assert disabled["installed"] and not disabled["running"]
    assert disabled["vault_enabled"] is False and disabled["actions"] == [] and disabled["surfaces"] == []
    assert disabled["configs"] == [] and host.calls == []
    for action in ("start", "stop", "restart", "invoke:read"):
        with pytest.raises(AppControlError):
            ctl.propose_action("obsidian", action, "ares")
    with pytest.raises(AppControlError):
        ctl.config_get("obsidian")

    vault = tmp_path / "private-vault"
    vault.mkdir()
    monkeypatch.setenv("JAEGER_OBSIDIAN_VAULT", str(vault))
    enabled = ctl.app_status("obsidian")
    assert enabled["vault_enabled"] is True
    assert enabled["surfaces"] == ["obsidian_list_notes", "obsidian_read_note", "obsidian_search_notes"]
    assert str(vault) not in str(enabled)
    vault.rmdir()
    assert ctl.app_status("obsidian")["vault_enabled"] is False
    vault.mkdir()
    link = tmp_path / "vault-link"
    link.symlink_to(vault, target_is_directory=True)
    monkeypatch.setenv("JAEGER_OBSIDIAN_VAULT", str(link))
    assert ctl.app_status("obsidian")["vault_enabled"] is False
    assert host.calls == []


@pytest.mark.parametrize("spec", default_specs(), ids=lambda s: s.id)
def test_every_adapter_status_and_proposals_with_fake_host(tmp_path, spec, monkeypatch):
    """Status, config read and action proposals for each real adapter spec; nothing executes."""
    host = FakeHost()
    if spec.configs:  # point configs at temp copies so the real files are never read
        cfgs = []
        for i, c in enumerate(spec.configs):
            p = tmp_path / f"cfg{i}.{c.fmt}"
            p.write_bytes(cf.dump(c.fmt if c.fmt != "jsonc" else "json", {"mcpServers": {}, "model": "m"}))
            cfgs.append(ConfigSpec(p, c.fmt, c.allow, c.rewritten_by_app, c.vendor_cli))
        spec = AppSpec(**{**spec.__dict__, "configs": tuple(cfgs)})
    ctl = _ctl(tmp_path, [spec], host)
    st = ctl.app_status(spec.id)
    assert st["installed"] and st["pending"] == []
    for act in spec.actions:
        p = ctl.propose_action(spec.id, act, "grokbot", prompt="hello" if act.startswith("invoke:") else "")
        assert p["status"] == "pending" and p["proposed_by"] == "grokbot"
    if spec.configs:
        assert ctl.config_get(spec.id)["config"]["model"] == "m"
    mutating = [c for c in host.calls if c[0] in ("open", "osascript", "codex", "claude", "gemini")
                or c[:2] in (["launchctl", "kickstart"], ["launchctl", "bootout"], ["launchctl", "bootstrap"])]
    assert mutating == []


# ── approvals ──

def test_workers_can_never_decide(tmp_path):
    ctl = _ctl(tmp_path, [mac()])
    p = ctl.propose_action("demo", "start", "ares")
    for name, prefix in (("ares", "ares:"), ("grokbot", "grokbot:"), ("muse", "muse:"), ("mcp", "mcp:"), ("bridge", None),
                         ("cli", None), (None, None)):
        with pytest.raises(AppControlError) as e:
            ctl.decide(p["id"], True, name, prefix, background=False)
        assert e.value.status == 403
    assert ctl.proposal(p["id"])["status"] == "pending"


def test_start_stop_restart_macapp(tmp_path):
    host = FakeHost()
    ev = []
    ctl = _ctl(tmp_path, [mac()], host, ev)
    p = ctl.propose_action("demo", "start", "grokbot")
    assert not any(c[0] == "open" for c in host.calls)  # proposing runs nothing
    out = ctl.decide(p["id"], True, "webui", background=False)
    assert out["status"] == "done" and ["open", "-b", "com.example.demo"] in host.calls
    host.running.add("demo")
    out = ctl.decide(ctl.propose_action("demo", "stop", "x")["id"], True, "webui", background=False)
    assert out["status"] == "done" and out["result"]["stopped"]
    assert ["osascript", "-e", 'quit app id "com.example.demo"'] in host.calls
    host.running.add("demo")
    out = ctl.decide(ctl.propose_action("demo", "restart", "x")["id"], True, "menubar", background=False)
    assert out["status"] == "done"
    assert [k for k, _ in ev].count("app.proposal") == 3 and "app.action" in [k for k, _ in ev]


def test_reject_runs_nothing_and_double_decide_refused(tmp_path):
    host = FakeHost()
    ctl = _ctl(tmp_path, [mac()], host)
    p = ctl.propose_action("demo", "start", "x")
    assert ctl.decide(p["id"], False, "webui")["status"] == "rejected"
    assert not any(c[0] == "open" for c in host.calls)
    with pytest.raises(AppControlError):
        ctl.decide(p["id"], True, "webui", background=False)


def test_launchd_adapter_and_self_service(tmp_path):
    host = FakeHost(running={"com.x.svc"})
    svc = AppSpec("svc", "svc", "launchd", label="com.x.svc")
    gw = AppSpec("gw", "gw", "launchd", label="com.x.gw", self_service=True)
    ctl = _ctl(tmp_path, [svc, gw], host)
    assert ctl.app_status("svc")["pid"] == 4242 and ctl.app_status("svc")["running"]
    out = ctl.decide(ctl.propose_action("svc", "restart", "x")["id"], True, "webui", background=False)
    assert out["status"] == "done" and ["launchctl", "kickstart", "-k", "gui/501/com.x.svc"] in host.calls
    ctl.decide(ctl.propose_action("svc", "stop", "x")["id"], True, "webui", background=False)
    assert ["launchctl", "bootout", "gui/501/com.x.svc"] in host.calls
    ctl.decide(ctl.propose_action("svc", "start", "x")["id"], True, "webui", background=False)
    assert host.calls[-2][:2] == ["launchctl", "bootstrap"] and host.calls[-1][:2] == ["launchctl", "kickstart"]
    with pytest.raises(AppControlError):
        ctl.propose_action("gw", "stop", "x")


def test_invoke_cli_and_cuadriver_disabled(tmp_path):
    host = FakeHost()
    specs = {s.id: s for s in default_specs()}
    ctl = _ctl(tmp_path, [specs["codex_cli"], specs["gemini_cli"], specs["claude_code"], specs["cuadriver"]], host)
    with pytest.raises(AppControlError):
        ctl.propose_action("codex_cli", "invoke:exec", "x", prompt="--dangerously-bypass")
    for app, act in (("codex_cli", "invoke:exec"), ("gemini_cli", "invoke:prompt"), ("claude_code", "invoke:prompt")):
        out = ctl.decide(ctl.propose_action(app, act, "x", prompt="summarize README")["id"], True, "webui", background=False)
        assert out["status"] == "done" and out["result"]["output"] == "fake output"
        assert host.calls[-1][-1] == "summarize README"
    assert ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "summarize README"] in host.calls
    assert not any(a.startswith("invoke") for a in specs["cuadriver"].actions)
    with pytest.raises(AppControlError):
        ctl.propose_action("cuadriver", "invoke:x", "x", prompt="p")


# ── config edits ──

def _cfg_app(tmp_path, fmt="json", rewritten=False, content=None, vendor=None, id="demo"):
    p = tmp_path / f"conf.{fmt}"
    p.write_bytes(content if content is not None else cf.dump(fmt if fmt != "jsonc" else "json", {"mcpServers": {"old": {"url": "o"}}, "keep": 1}))
    return p, mac(id, cfg=(ConfigSpec(p, fmt, ("mcpServers.*",), rewritten, vendor),))


@pytest.mark.parametrize("fmt", ["json", "jsonc", "toml", "plist"])
def test_config_apply_backup_and_rollback(tmp_path, fmt):
    path, spec = _cfg_app(tmp_path, fmt)
    before = path.read_bytes()
    ctl = _ctl(tmp_path, [spec])
    p = ctl.propose_config("demo", [{"op": "set", "path": "mcpServers.jaeger", "value": {"url": "http://127.0.0.1:8792/mcp",
                                     "headers": {"Authorization": "Bearer secretsecretsecret"}}}], "grokbot")
    assert path.read_bytes() == before  # proposal never writes
    assert "secretsecret" not in json.dumps(ctl.proposals())
    out = ctl.decide(p["id"], True, "webui", background=False)
    assert out["status"] == "done", out
    data = cf.parse(fmt, path.read_bytes())
    assert data["mcpServers"]["jaeger"]["url"].endswith("/mcp") and data["keep"] == 1
    bdir = Path(out["result"]["backup"])
    assert (bdir / "ROLLBACK.sh").stat().st_mode & 0o777 == 0o700
    assert (bdir / path.name).read_bytes() == before and (bdir / path.name).stat().st_mode & 0o777 == 0o600
    with pytest.raises(AppControlError):
        ctl.rollback(p["id"], "grokbot", "grokbot:")
    assert ctl.rollback(p["id"], "webui")["status"] == "rolled_back"
    assert path.read_bytes() == before


def test_rollback_script_restores(tmp_path):
    path, spec = _cfg_app(tmp_path)
    before = path.read_bytes()
    ctl = _ctl(tmp_path, [spec])
    out = ctl.decide(ctl.propose_config("demo", [{"op": "delete", "path": "mcpServers.old"}], "x")["id"], True, "webui", background=False)
    assert path.read_bytes() != before
    subprocess.run(["/bin/sh", out["result"]["rollback"]], check=True, capture_output=True)
    assert path.read_bytes() == before


def test_refuses_write_while_self_rewriting_app_runs(tmp_path):
    path, spec = _cfg_app(tmp_path, rewritten=True)
    host = FakeHost(running={"demo"})
    ctl = _ctl(tmp_path, [spec], host)
    before = path.read_bytes()
    out = ctl.decide(ctl.propose_config("demo", [{"op": "delete", "path": "mcpServers.old"}], "x")["id"], True, "webui", background=False)
    assert out["status"] == "failed" and "quit it first" in out["error"]
    assert path.read_bytes() == before and not (tmp_path / "state/backups").exists()


def test_parse_check_auto_rollback(tmp_path, monkeypatch):
    path, spec = _cfg_app(tmp_path)
    before = path.read_bytes()
    ctl = _ctl(tmp_path, [spec])
    p = ctl.propose_config("demo", [{"op": "delete", "path": "mcpServers.old"}], "x")
    monkeypatch.setattr(cf, "dump", lambda fmt, data, original=b"": b"{broken")
    out = ctl.decide(p["id"], True, "webui", background=False)
    assert out["status"] == "failed" and "rolled back" in out["error"]
    assert path.read_bytes() == before


def test_disallowed_keys_and_readonly_configs(tmp_path):
    path, spec = _cfg_app(tmp_path)
    ro = mac("ro", cfg=(ConfigSpec(path, "json", ()),))
    ctl = _ctl(tmp_path, [spec, ro, mac("opaque")])
    with pytest.raises(AppControlError) as e:
        ctl.propose_config("demo", [{"op": "set", "path": "keep", "value": 2}], "x")
    assert e.value.status == 403
    with pytest.raises(AppControlError):
        ctl.propose_config("ro", [{"op": "set", "path": "mcpServers.x", "value": 1}], "x")
    with pytest.raises(AppControlError) as e:
        ctl.config_get("opaque")
    assert e.value.status == 404


def test_jsonc_with_comments_refused_at_proposal(tmp_path):
    path, spec = _cfg_app(tmp_path, "jsonc", content=b'{\n // mine\n "mcpServers": {}\n}')
    with pytest.raises(AppControlError) as e:
        _ctl(tmp_path, [spec]).propose_config("demo", [{"op": "set", "path": "mcpServers.x", "value": {}}], "x")
    assert e.value.status == 409


def test_claude_code_uses_vendor_cli_not_file_edit(tmp_path):
    path, spec = _cfg_app(tmp_path, vendor="claude", id="claude_code")
    before = path.read_bytes()
    host = FakeHost()
    ctl = _ctl(tmp_path, [spec], host)
    out = ctl.decide(ctl.propose_config("claude_code", [{"op": "set", "path": "mcpServers.jaeger", "value": {"type": "http", "url": "u"}}],
                                        "x")["id"], True, "webui", background=False)
    assert out["status"] == "done" and out["result"]["via"] == "claude CLI"
    assert path.read_bytes() == before
    assert ["claude", "mcp", "add-json", "-s", "user", "jaeger", '{"type": "http", "url": "u"}'] in host.calls


def test_config_read_is_redacted(tmp_path):
    path, spec = _cfg_app(tmp_path, content=json.dumps({"mcpServers": {"j": {"headers": {"Authorization": "Bearer zzzzzzzzzzzzzzzz"}}}}).encode())
    got = _ctl(tmp_path, [spec]).config_get("demo")
    assert "zzzz" not in json.dumps(got)


# ── auth wiring ──

def test_route_scopes():
    assert caller_auth.required_scope("POST", "/v1/apps/{app}/proposals") == "turn"
    assert caller_auth.required_scope("POST", "/v1/apps/proposals/{pid}/decision") == "approve"
    assert caller_auth.required_scope("POST", "/v1/apps/proposals/{pid}/rollback") == "approve"
    assert caller_auth.prefixed_route_allowed("GET", "/v1/apps/{app}/config", "muse")
    assert caller_auth.prefixed_route_allowed("POST", "/v1/apps/{app}/proposals", "grokbot")
    assert not caller_auth.prefixed_route_allowed("POST", "/v1/apps/proposals/{pid}/decision", "grokbot")
    assert not caller_auth.prefixed_route_allowed("POST", "/v1/apps/{app}/proposals", "rackpc")
    for name, spec in caller_auth.CALLERS.items():
        if spec.session_prefix is not None:
            assert "approve" not in spec.scopes, name


def test_http_routes_end_to_end(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_ai.features.app_control import routes

    path, spec = _cfg_app(tmp_path)
    host = FakeHost()
    ctl = _ctl(tmp_path, [spec], host)

    async def go():
        who = {"caller": SimpleNamespace(name="grokbot", session_prefix="grokbot:")}

        @web.middleware
        async def mw(request, handler):
            request["caller"] = who["caller"]
            return await handler(request)
        app = web.Application(middlewares=[mw])
        routes.register(SimpleNamespace(app=app, event_bus=SimpleNamespace(publish=lambda *a: None)), control=ctl)
        async with TestClient(TestServer(app)) as c:
            assert (await (await c.get("/v1/apps")).json())["apps"][0]["id"] == "demo"
            r = await c.post("/v1/apps/demo/proposals", json={"action": "start"})
            pid = (await r.json())["id"]
            r = await c.post(f"/v1/apps/proposals/{pid}/decision", json={"approve": True})
            assert r.status == 403
            who["caller"] = SimpleNamespace(name="webui", session_prefix=None)
            r = await c.post(f"/v1/apps/proposals/{pid}/decision", json={"approve": True})
            assert r.status == 200
            for _ in range(50):
                st = (await (await c.get(f"/v1/apps/proposals/{pid}")).json())["status"]
                if st in ("done", "failed"):
                    break
                await asyncio.sleep(0.02)
            assert st == "done"
            assert (await c.get("/v1/apps/nope")).status == 404
    asyncio.run(go())
