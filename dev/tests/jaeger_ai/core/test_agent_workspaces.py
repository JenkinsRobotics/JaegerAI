import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from jaeger_ai.core.runtime import agent_workspaces as aw
from jaeger_ai.core.runtime.host_environment import snapshot

ROOT = Path(__file__).resolve().parents[4]


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configuration():
    return {
        "id": aw.LEGACY_CONTAINERS["hermes"],
        "initProcess": {"user": {"raw": {"userString": "root"}}, "workingDirectory": "/apptoo",
                        "executable": "/init.sh", "arguments": [], "environment": ["PRESERVE=this"]},
        "image": {"reference": "old-image"}, "resources": {"cpus": 4, "memoryInBytes": 4294967296},
        "networks": [{"network": "default", "options": {"mtu": 1280}}],
        "publishedPorts": [{"hostAddress": "127.0.0.1", "hostPort": 8787, "containerPort": 8787, "proto": "tcp"}],
        "mounts": [{"type": {"virtiofs": {}}, "source": "/existing", "destination": "/workspace", "options": []}],
    }


def test_mount_plan_preserves_launch_contract_and_adds_explicit_rw_mount(monkeypatch, tmp_path):
    monkeypatch.setattr(aw, "workspace_mounts", lambda home, **kwargs: [(tmp_path, "/mnt/host/GitHub")])
    args = aw.create_arguments(configuration(), "hermes")
    assert args[args.index("--user") + 1] == "root"
    assert "PRESERVE=this" in args
    assert "/existing:/workspace" in args
    assert f"{tmp_path}:/mnt/host/GitHub" in args
    assert "127.0.0.1:8787:8787/tcp" in args
    assert "--ssh" not in args


def test_missing_share_is_not_replaced_with_empty_directory(monkeypatch, tmp_path):
    missing = tmp_path / "absent-nas"
    monkeypatch.setattr(aw, "workspace_mounts", lambda home, **kwargs: [(missing, "/mnt/nas/share")])
    with pytest.raises(ValueError, match="not mounted/present"):
        aw.create_arguments(configuration(), "hermes")
    assert not missing.exists()


def test_unknown_privileges_fail_closed():
    config = configuration()
    config["ssh"] = True
    with pytest.raises(ValueError, match="manual review"):
        aw.create_arguments(config, "hermes")


def test_manifest_fallback_and_role_isolation(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    monkeypatch.setattr(aw, "STATE_PATH", path)
    assert aw.container_name("hermes") == aw.LEGACY_CONTAINERS["hermes"]
    path.write_text(json.dumps({"containers": {"hermes": aw.MANAGED_CONTAINERS["hermes"]}}))
    assert aw.container_name("hermes") == aw.MANAGED_CONTAINERS["hermes"]
    assert aw.container_name("openclaw") == aw.LEGACY_CONTAINERS["openclaw"]
    path.write_text(json.dumps({"containers": {"hermes": "unrelated-user-container"}}))
    with pytest.raises(ValueError):
        aw.container_name("hermes")


def test_live_inventory_does_not_claim_a_write_test():
    result = snapshot(["/approved"])
    assert result["approved_roots"] == ["/approved"]
    assert "not proof" in result["access_note"]
    assert result["host"]["os"]
    assert result["observed_at"]


def test_cloud_stop_compatibility_is_narrow_and_idempotent():
    spec = importlib.util.spec_from_file_location("jaeger_agent_compat", ROOT / "integrations/hermes_webui/jaeger_agent_compat.py")
    compat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compat)
    class Agent:
        model = "glm-5.3-flash:cloud"
        def _is_ollama_glm_backend(self): return True
        def _should_treat_stop_as_truncated(self, reason, message, messages=None): return True
    compat.install(Agent)
    wrapped = Agent._should_treat_stop_as_truncated
    assert not Agent()._should_treat_stop_as_truncated("stop", "- Terminal: Linux")
    assert Agent()._should_treat_stop_as_truncated("length", "partial")
    local = Agent()
    local.model = "glm-local"
    assert local._should_treat_stop_as_truncated("stop", "partial")
    compat.install(Agent)
    assert Agent._should_treat_stop_as_truncated is wrapped


def test_managed_context_is_idempotent_and_preserves_user_notes():
    installer = script("setup-agent-workspaces")
    block = "<!-- JAEGER-MAC-CONNECTION-BEGIN -->\nCURRENT\n<!-- JAEGER-MAC-CONNECTION-END -->"
    once = installer.managed_context("My original notes\n", block)
    assert installer.managed_context(once, block) == once
    assert "My original notes" in once
    with pytest.raises(ValueError):
        installer.managed_context("<!-- JAEGER-MAC-CONNECTION-BEGIN -->broken", block)


def test_write_probe_removes_only_its_own_files(tmp_path):
    checker = script("agent-mac-check")
    sentinel = tmp_path / "user-file.txt"
    sentinel.write_text("preserve")
    assert checker.write_probe(tmp_path)["ok"]
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_text() == "preserve"


def test_configure_preserves_models_keys_and_rollback(monkeypatch, tmp_path):
    installer = script("setup-agent-workspaces")
    home, repo, backup = tmp_path / "home", tmp_path / "repo", tmp_path / "backup"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(aw, "REPO_ROOT", repo)
    configs = [home / ".hermes/config.yaml"] + [home / f".hermes/profiles/{role}/config.yaml" for role in ("jaeger", "roundtable", "openclaw")]
    for path in configs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("model:\n  provider: ollama\n  default: keep-this-model\nmcp_servers:\n  jaeger-host:\n    url: http://old-host:8811/mcp\n")
    gateway = home / ".ares/gateway/config.yaml"
    gateway.parent.mkdir(parents=True)
    gateway.write_text(yaml.safe_dump({"mcp": {"policies": {"existing": "preserved"}, "targets": [{"name": "host-openclaw", "stdio": {"env": {"ARES_CAPABILITY_IDENTITY": "hermes"}}}]}}))
    for path, content in [(home / ".hermes/SOUL.md", "USER SOUL"),
                          (home / ".ares/openclaw/workspace/TOOLS.md", "USER TOOLS"),
                          (home / "bin/hermes", "#!/bin/sh\necho original"),
                          (repo / "scripts/hermes-container", "#!/usr/bin/env python3"),
                          (repo / "integrations/agent_workspaces/AGENT_CONTEXT.md", "<!-- JAEGER-MAC-CONNECTION-BEGIN -->\nCURRENT\n<!-- JAEGER-MAC-CONNECTION-END -->"),
                          (repo / ".jaeger_ai/instances/jaeger/config.yaml", "model: preserved\ncontainers:\n  hermes_webui_container: hermes-webui-hermes-webui\n")]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    wrapper = home / "bin/hermes"
    wrapper.chmod(0o755)
    installer.configure(backup)
    assert (home / ".hermes/workspaces.json").exists()
    assert not (home / ".hermes/webui_state/workspaces.json").exists()
    for path in configs:
        result = yaml.safe_load(path.read_text())
        assert result["model"] == {"provider": "ollama", "default": "keep-this-model"}
        assert result["mcp_servers"]["jaeger-host"]["url"] == "http://192.168.64.1:8811/mcp"
    assert yaml.safe_load(gateway.read_text())["mcp"]["policies"] == {"existing": "preserved"}
    assert wrapper.is_symlink()
    installer.restore_configuration(backup)
    assert not wrapper.is_symlink()
    assert wrapper.stat().st_mode & 0o777 == 0o755
    assert "echo original" in wrapper.read_text()
    assert (home / ".hermes/SOUL.md").read_text() == "USER SOUL"
    assert len(yaml.safe_load(gateway.read_text())["mcp"]["targets"]) == 1
