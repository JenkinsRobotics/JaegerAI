"""Empty execution workspace verifies against the effective instance workspace, not the Gateway cwd."""
from __future__ import annotations

import hashlib
import time
from types import SimpleNamespace

import jaeger_agent.core.workspace as ws_mod
from jaeger_ai.core.tasks.owner import GatewayTaskOwner


def _task(workspace, created):
    return SimpleNamespace(payload={"execution": {"workspace": workspace}}, created_at=created, goal="")


def _result(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"task_completion": {"ok": True, "verification_receipts": [
        {"kind": "file_sha256", "path": str(path), "sha256": digest}]}}


def test_empty_workspace_uses_effective_instance_workspace(tmp_path, monkeypatch):
    inst = tmp_path / "instances" / "jaeger" / "workspace"
    inst.mkdir(parents=True)
    other = tmp_path / "repo"
    other.mkdir()
    monkeypatch.chdir(other)  # the Gateway process cwd must not be the root
    monkeypatch.setattr(ws_mod, "get_effective_workspace_dir", lambda: inst)
    created = time.time() - 5
    out = inst / "result.md"
    out.write_text("1+2+3=6\n")
    ok, evidence = GatewayTaskOwner.verify(_task("", created), _result(out))
    assert ok is True, evidence
    assert evidence[0]["path"] == str(out)


def test_empty_workspace_still_rejects_paths_outside_instance(tmp_path, monkeypatch):
    inst = tmp_path / "ws"
    inst.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ws_mod, "get_effective_workspace_dir", lambda: inst)
    out = tmp_path / "outside.md"
    out.write_text("x")
    ok, evidence = GatewayTaskOwner.verify(_task("", time.time() - 5), _result(out))
    assert ok is False and "outside workspace" in evidence


def test_explicit_workspace_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_mod, "get_effective_workspace_dir", lambda: tmp_path / "nope")
    out = tmp_path / "r.md"
    out.write_text("ok")
    ok, _ = GatewayTaskOwner.verify(_task(str(tmp_path), time.time() - 5), _result(out))
    assert ok is True


def test_no_resolvable_workspace_fails_closed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ws_mod, "get_effective_workspace_dir", lambda: None)
    out = tmp_path / "r.md"
    out.write_text("ok")
    ok, evidence = GatewayTaskOwner.verify(_task("", time.time() - 5), _result(out))
    assert ok is False and "No workspace" in evidence
