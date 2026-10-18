"""Gateway turns confine read/list/search tools to the session workspace."""
from __future__ import annotations

import os

import pytest

from jaeger_agent.core.workspace import (
    SandboxError, _resolve_read, active_read_roots, project_scope, read_confinement,
)


@pytest.fixture
def tree(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "a.txt").write_text("a")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    (ws / "link").symlink_to(outside)  # symlink escaping the workspace
    return ws, outside


def test_reads_confined_to_workspace(tree):
    ws, outside = tree
    with project_scope(ws), read_confinement([ws]):
        assert active_read_roots() == (__import__("pathlib").Path(os.path.realpath(ws)),)
        assert _resolve_read("src/a.txt").read_text() == "a"
        assert _resolve_read(str(ws / "src")).is_dir()
        for bad in (str(outside / "secret.txt"), "../outside/secret.txt", "link/secret.txt",
                    os.path.expanduser("~"), "/etc"):
            with pytest.raises(SandboxError, match="outside this session's workspace"):
                _resolve_read(bad)
    assert active_read_roots() is None
    assert _resolve_read(str(outside / "secret.txt")).read_text() == "s"  # unconfined outside a turn


def test_search_and_list_tools_refuse_outside(tree, tmp_path, monkeypatch):
    from jaeger_agent.core import workspace
    from jaeger_agent.tools import files
    inst = workspace.DefaultWorkspace(tmp_path / "inst")
    for d in (inst.logs_dir, inst.skills_dir, inst.workspace_dir):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(workspace, "_layout", inst)
    ws, outside = tree
    with project_scope(ws), read_confinement([ws]):
        listed = files.list_skill_dir(str(outside))
        searched = files.search_files("s", path=str(outside))
        inside = files.search_files("a", path=str(ws))
    assert not listed.get("ok", True) or "error" in listed
    assert not searched.get("ok", True) or "error" in searched
    assert "outside" in str(listed) and "outside" in str(searched)
    assert inside.get("ok", True) is not False


def test_gateway_read_roots(tmp_path):
    from types import SimpleNamespace
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    layout = SimpleNamespace(workspace_dir=tmp_path / "iw", skills_dir=tmp_path / "skills")
    rt = SimpleNamespace(layout=layout)
    roots = JaegerGatewayApp._read_roots(rt, {"workspace": "/private/tmp/x"})
    assert roots == ["/private/tmp/x", str(tmp_path / "skills")]
    assert JaegerGatewayApp._read_roots(rt, {})[-1] == str(tmp_path / "skills")
