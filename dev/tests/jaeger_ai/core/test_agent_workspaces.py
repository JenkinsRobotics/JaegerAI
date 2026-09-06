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


def test_expansion_preserves_existing_github_mount_and_original_container(monkeypatch, tmp_path):
    github, personal = tmp_path/'github', tmp_path/'documents'
    github.mkdir(); personal.mkdir()
    config = configuration()
    config['id'] = aw.MANAGED_CONTAINERS['hermes']
    config['mounts'].append({'type':{'virtiofs':{}}, 'source':str(github), 'destination':'/mnt/host/GitHub', 'options':[]})
    monkeypatch.setattr(aw, 'workspace_mounts', lambda home, **kw: [(github,'/mnt/host/GitHub'),(personal,'/mnt/host/Documents')])
    args = aw.create_arguments(config, 'hermes', include_personal=True, expand=True)
    assert args[args.index('--name')+1] == aw.EXPANDED_CONTAINERS['hermes']
    assert args.count(f'{github}:/mnt/host/GitHub') == 1
    assert f'{personal}:/mnt/host/Documents' in args
    assert config['id'] == aw.MANAGED_CONTAINERS['hermes']
    config['mounts'][-1]['options'] = ['ro']
    with pytest.raises(ValueError, match='Conflicting'):
        aw.create_arguments(config, 'hermes', include_personal=True, expand=True)


def test_expanded_container_manifest_is_role_scoped(monkeypatch, tmp_path):
    path = tmp_path/'state.json'
    monkeypatch.setattr(aw, 'STATE_PATH', path)
    path.write_text(json.dumps({'containers':aw.EXPANDED_CONTAINERS}))
    assert aw.container_name('hermes') == aw.EXPANDED_CONTAINERS['hermes']
    path.write_text(json.dumps({'containers':{'hermes':aw.EXPANDED_CONTAINERS['openclaw']}}))
    with pytest.raises(ValueError): aw.container_name('hermes')


@pytest.mark.parametrize('failure', ['verify', 'publish'])
def test_expansion_transaction_restores_originals_on_failure(failure):
    installer = script('expand-agent-workspaces')
    calls, restored = [], []
    plans = {role:['create','--name',name] for role,name in aw.EXPANDED_CONTAINERS.items()}
    def verify(role,name):
        calls.append(('verified',name))
        if failure == 'verify' and role == 'openclaw': raise RuntimeError('probe failed')
    def publish():
        calls.append(('publish',))
        if failure == 'publish': raise RuntimeError('write failed')
    with pytest.raises(RuntimeError, match='restored'):
        installer.transition(plans,aw.MANAGED_CONTAINERS,invoke=lambda *args:calls.append(args),
                             verify=verify,publish=publish,restore=lambda:restored.append(True))
    assert restored == [True]
    for name in aw.MANAGED_CONTAINERS.values(): assert ('start',name) in calls
    for name in aw.EXPANDED_CONTAINERS.values(): assert ('stop','--time','10',name) in calls
    assert not any(call[0] in ('delete','rm','prune') for call in calls)


def test_expansion_publishes_only_after_both_replacements_verify():
    installer = script('expand-agent-workspaces')
    calls=[]
    plans={role:['create','--name',name] for role,name in aw.EXPANDED_CONTAINERS.items()}
    installer.transition(plans,aw.MANAGED_CONTAINERS,invoke=lambda *args:calls.append(args),
                         verify=lambda role,name:calls.append(('verified',role)),
                         publish=lambda:calls.append(('publish',)), restore=lambda:pytest.fail('Unexpected rollback'))
    assert calls[-2:] == [('verified','openclaw'),('publish',)]


def test_expansion_refuses_active_or_unknown_work():
    installer=script('expand-agent-workspaces')
    idle={'active_runs':0,'active_streams':0}
    installer.ensure_idle(idle,{'tasks':{'active':0}})
    for webui,native in [({},{}),(idle,{}),(idle,{'tasks':{'active':1}}),({'active_runs':1,'active_streams':0},{'tasks':{'active':0}})]:
        with pytest.raises(RuntimeError,match='work'):
            installer.ensure_idle(webui,native)


def test_failed_access_probe_retains_private_receipt(monkeypatch, tmp_path):
    installer = script('expand-agent-workspaces')
    import subprocess
    receipt = {'checks': {'write:/mnt/host/Documents': {'ok': False, 'error': 'PermissionError'}}}
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(
        a, 1, json.dumps(receipt), 'private diagnostic'))
    destination = tmp_path / 'probe.json'
    with pytest.raises(RuntimeError, match='write:/mnt/host/Documents'):
        installer.access_probe('hermes', 'test-container', destination)
    saved = json.loads(destination.read_text())
    assert saved['receipt'] == receipt
    assert saved['exit_code'] == 1
    assert destination.stat().st_mode & 0o777 == 0o600


def test_access_probe_does_not_print_private_stderr(monkeypatch, tmp_path):
    installer = script('expand-agent-workspaces')
    import subprocess
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(
        a, 1, '', 'PRIVATE-SECRET'))
    with pytest.raises(RuntimeError) as error:
        installer.access_probe('hermes', 'test-container', tmp_path / 'probe.json')
    assert 'PRIVATE-SECRET' not in str(error.value)


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


def test_write_probe_retries_transient_network_directory_cleanup(monkeypatch, tmp_path):
    import errno
    checker = script('agent-mac-check')
    original = Path.rmdir
    attempts = []
    def delayed_rmdir(path):
        attempts.append(path)
        if len(attempts) < 3:
            raise OSError(errno.ENOTEMPTY, 'SMB deferred unlink')
        return original(path)
    monkeypatch.setattr(Path, 'rmdir', delayed_rmdir)
    monkeypatch.setattr(checker.time, 'sleep', lambda _: None)
    assert checker.write_probe(tmp_path)['ok']
    assert len(attempts) == 3
    assert list(tmp_path.iterdir()) == []


def test_write_probe_cleanup_does_not_mask_failed_operation(monkeypatch, tmp_path):
    import errno
    checker = script('agent-mac-check')
    monkeypatch.setattr(Path, 'read_text', lambda *a, **kw: (_ for _ in ()).throw(
        FileNotFoundError(errno.ENOENT, 'renamed file absent')))
    monkeypatch.setattr(Path, 'rmdir', lambda *a: (_ for _ in ()).throw(
        OSError(errno.ENOTEMPTY, 'cleanup failed')))
    monkeypatch.setattr(checker.time, 'sleep', lambda _: None)
    with pytest.raises(FileNotFoundError) as error:
        checker.write_probe(tmp_path)
    assert error.value.probe_stage == 'read_after_rename'
    assert error.value.cleanup_error == 'OSError'


@pytest.mark.parametrize('target', [
    '/Volumes/Jenkins_Robotics', '/Users/matthewjenkins/Documents',
    '/Volumes/Personal-Drive/.jaeger-mcp-probe-' + 'a' * 32 + '/../user-file',
])
def test_host_nas_probe_refuses_non_probe_targets(target):
    with pytest.raises(ValueError): script('verify-host-nas').validate_path(target)


def test_host_nas_probe_accepts_only_exact_scoped_directory():
    target = '/Volumes/Jenkins_Robotics/.jaeger-mcp-probe-' + 'a' * 32
    assert script('verify-host-nas').validate_path(target) == target


def test_host_nas_probe_refuses_unknown_identity_before_reading_credentials():
    with pytest.raises(ValueError, match='role'):
        script('verify-host-nas').check('unknown', '/Volumes/Jenkins_Robotics/.jaeger-mcp-probe-' + 'a' * 32)


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
