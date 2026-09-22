import json
from types import SimpleNamespace

import pytest

from jaeger_ai.features.webui.server_controls import ServerControls, SERVICES


def test_webui_ready_probe_does_not_require_auth():
    """Auth-gated /api/profiles returns 401 and was marking a live WebUI down."""
    assert SERVICES["webui"][2] == 8790
    assert SERVICES["webui"][3] == "/health"


@pytest.fixture
def controls(tmp_path, monkeypatch):
    calls = []
    def execute(args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps([{'status': {'state': 'stopped'}}]), stderr='')
    c = ServerControls(tmp_path, execute)
    monkeypatch.setattr(c, 'status', lambda: [])
    monkeypatch.setattr(c, 'container', lambda role: 'test-' + role)
    for service, (_, label, _, _) in SERVICES.items():
        if label:
            p = c.plist(service); p.parent.mkdir(parents=True, exist_ok=True);p.write_text('test')
    c.calls = calls
    return c


def test_start_unloaded_job_bootstraps_configured_plist(controls, monkeypatch):
    monkeypatch.setattr(controls, 'loaded', lambda label: False)
    assert controls.change('webui', 'start')['ok']
    assert controls.calls == [['/bin/launchctl', 'bootstrap', controls.domain, str(controls.plist('webui'))]]


def test_stop_unloads_keepalive_job_instead_of_respawning_it(controls):
    assert controls.change('runner', 'stop')['ok']
    assert controls.calls[-1] == ['/bin/launchctl', 'bootout', controls.domain + '/' + SERVICES['runner'][1]]


def test_start_running_job_does_not_kill_it(controls):
    assert controls.change('agent', 'start')['ok']
    assert '-k' not in controls.calls[-1]


def test_stop_all_reverses_dependency_order(controls, monkeypatch):
    seen = []
    monkeypatch.setattr(controls, 'change_one', lambda service, action: seen.append(service))
    assert controls.change('all', 'stop')['ok']
    assert seen == list(reversed(SERVICES))


def test_hermes_agent_uses_native_launch_agent_only(controls):
    assert controls.change('hermes', 'start')['ok']
    assert controls.calls == [
        ['/bin/launchctl', 'print', controls.domain + '/' + SERVICES['hermes'][1]],
        ['/bin/launchctl', 'kickstart', controls.domain + '/' + SERVICES['hermes'][1]]
    ]


def test_container_daemon_start_and_stop(controls):
    assert controls.change('container', 'start')['ok']
    assert controls.calls[-1] == ['/opt/homebrew/bin/container', 'system', 'start', '--disable-kernel-install']
    assert controls.change('container', 'stop')['ok']
    assert controls.calls[-1] == ['/opt/homebrew/bin/container', 'system', 'stop']


def test_unknown_command_never_executes(controls):
    with pytest.raises(ValueError):controls.change('arbitrary-label', 'start')
    assert controls.calls == []


def test_partial_failure_is_visible_and_other_services_continue(controls, monkeypatch):
    seen = []
    def change(service, action):
        seen.append(service)
        if service == 'gateway':raise RuntimeError('test failure')
    monkeypatch.setattr(controls, 'change_one', change)
    result = controls.change('all', 'start')
    assert not result['ok'] and 'test failure' in result['error']
    assert seen == list(SERVICES)


def test_change_reset_delegates_to_stack_reset(controls, monkeypatch):
    called = []
    monkeypatch.setattr(
        "jaeger_ai.core.runtime.stack.stack_reset",
        lambda timeout_s=60.0: called.append(timeout_s) or {"ok": True, "step": "completed"},
    )
    result = controls.change("all", "reset")
    assert result["ok"] is True
    assert called == [60.0]

