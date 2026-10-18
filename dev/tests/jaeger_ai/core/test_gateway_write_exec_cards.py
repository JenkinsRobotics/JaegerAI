"""Gateway-turn policy: writes and code/shell execution need a card unless a
project grant covers the target or the owner granted this session."""
from __future__ import annotations

from types import SimpleNamespace

from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.gateway.server import JaegerGatewayApp, _GatewayToolConfirmationProvider
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_os.core.safety.permissions import PermissionRequest, PermissionTier


class _AllGranted:
    def is_granted(self, skill):  # a permissions.json with files/code/shell "always"
        return True


def _provider(tmp_path, monkeypatch, autonomy="scoped"):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "g.sqlite3"))
    app.store.ensure_session("s")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"automation:\n  autonomy: {autonomy}\n")
    (tmp_path / "authority_policy.yaml").write_text("filesystem:\n  write: true\n")
    layout = SimpleNamespace(config_path=cfg, root=tmp_path)
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: SimpleNamespace(layout=layout)))
    p = _GatewayToolConfirmationProvider(app, "s", "r")
    p.prompts = []
    monkeypatch.setattr(p, "_grants", lambda: _AllGranted())
    monkeypatch.setattr(p, "_prompt", lambda req: p.prompts.append(req.operation) or False)
    return p


WRITE = PermissionRequest(tier=PermissionTier.WRITE_LOCAL, skill="files", operation="write_file", arguments={"path": "notes/x.md"})
CODE = PermissionRequest(tier=PermissionTier.PRIVILEGED, skill="code", operation="execute_code", arguments={"code": "1"})
SHELL = PermissionRequest(tier=PermissionTier.PRIVILEGED, skill="shell", operation="run_shell", arguments={"command": "ls"})
READ = PermissionRequest(tier=PermissionTier.READ_ONLY, skill="files", operation="read_file", arguments={"path": "a"})


def test_persistent_always_grants_do_not_skip_the_card_for_writes_and_exec(tmp_path, monkeypatch):
    p = _provider(tmp_path, monkeypatch)
    assert p.confirm(WRITE) is False and p.confirm(CODE) is False and p.confirm(SHELL) is False
    assert p.prompts == ["write_file", "execute_code", "run_shell"]


def test_read_tools_stay_unprompted(tmp_path, monkeypatch):
    p = _provider(tmp_path, monkeypatch)
    assert p.confirm(READ) is True and p.prompts == []


def test_session_grant_or_project_grant_covers_it(tmp_path, monkeypatch):
    p = _provider(tmp_path, monkeypatch)
    p._grant_for_session("files")
    assert p.confirm(WRITE) is True
    monkeypatch.setattr(p.app, "_project_grant_allows", lambda sid, req: req.operation == "execute_code")
    assert p.confirm(CODE) is True
    assert p.confirm(SHELL) is False and p.prompts == ["run_shell"]


def test_explicit_autonomy_auto_is_still_honored(tmp_path, monkeypatch):
    p = _provider(tmp_path, monkeypatch, autonomy="auto")
    assert p.confirm(WRITE) is True and p.prompts == []
