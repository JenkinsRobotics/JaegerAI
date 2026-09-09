"""Operator lifecycle regressions; all process and deployment effects are isolated."""
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from jaeger_ai.cli.verbs import lifecycle_verbs as lifecycle


@pytest.fixture(autouse=True)
def isolate_gateway(monkeypatch):
    import jaeger_ai.features.gateway.service as gateway
    monkeypatch.setattr(gateway, 'start', lambda: {'ok': True})
    monkeypatch.setattr(gateway, 'stop', lambda: {'ok': True})


def test_restart_dry_run_never_performs_real_stop_or_start(monkeypatch):
    calls = []
    monkeypatch.setattr(lifecycle, '_cmd_stop_argv', lambda args: calls.append(('stop', args)) or 0)
    monkeypatch.setattr(lifecycle, '_cmd_start_argv', lambda args: calls.append(('start', args)) or 0)
    monkeypatch.setattr(lifecycle.time, 'sleep', lambda _: None)
    assert lifecycle._cmd_restart_argv(['--dry-run', '--no-app']) == 0
    assert all('--dry-run' in args and '--no-app' in args for _, args in calls)


def test_restart_rejects_unknown_flags_before_stopping(monkeypatch):
    monkeypatch.setattr(lifecycle, '_cmd_stop_argv', lambda _: pytest.fail('must not stop'))
    with pytest.raises(SystemExit):
        lifecycle._cmd_restart_argv(['--typo'])


def test_stop_failure_is_reported_and_restart_does_not_start(monkeypatch, capsys):
    label = lifecycle.SUPERVISOR_SERVICE
    monkeypatch.setattr(lifecycle, '_get_launchd_jobs', lambda: {label: {'pid': 1, 'status': 0}})
    monkeypatch.setattr(lifecycle, '_find_app_pids', lambda: [])
    monkeypatch.setattr(lifecycle.subprocess, 'run', lambda *a, **kw: CompletedProcess(a[0], 1, '', 'failed'))
    monkeypatch.setattr(lifecycle, '_cmd_start_argv', lambda _: pytest.fail('must not start after failed stop'))
    assert lifecycle._cmd_restart_argv(['--no-app', '--no-containers']) == 1
    assert 'stack is stopped' not in capsys.readouterr().out


@pytest.mark.parametrize("warmup_polls", [0, 20])
def test_start_preserves_loaded_services_and_running_containers(monkeypatch, tmp_path, warmup_polls):
    import jaeger_ai.features.gateway.service as gateway
    agents = tmp_path / 'Library/LaunchAgents'
    agents.mkdir(parents=True)
    for label, _, _ in lifecycle.SERVICES_ORDERED:
        (agents / (label + '.plist')).write_text('test')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(lifecycle, '_get_launchd_jobs', lambda: {
        label: {'pid': 10, 'status': 0} for label, _, _ in lifecycle.SERVICES_ORDERED
    })
    monkeypatch.setattr(lifecycle, '_get_containers_state', lambda: {
        name: {'state': 'running', 'ip': '127.0.0.1'} for name in lifecycle._container_names()
    })
    monkeypatch.setattr(lifecycle, '_get_container_cli', lambda: '/container')
    monkeypatch.setattr(lifecycle, '_is_port_open', lambda *a, **kw: True)
    polls = 0
    def ready(*args, **kwargs):
        nonlocal polls
        polls += 1
        return polls > warmup_polls
    monkeypatch.setattr(lifecycle, '_service_port_open', ready)
    monkeypatch.setattr(lifecycle.time, 'sleep', lambda _: None)
    monkeypatch.setattr(gateway, 'start', lambda: {'ok': True, 'already_running': True})
    calls = []
    monkeypatch.setattr(lifecycle.subprocess, 'run', lambda cmd, **kw: calls.append(cmd) or CompletedProcess(cmd, 0, '', ''))
    assert lifecycle._cmd_start_argv(['--no-app']) == 0
    assert not any('bootout' in c or 'bootstrap' in c or 'start' in c for c in calls)


def test_container_names_follow_deployment_manifest(monkeypatch):
    from jaeger_ai.core.runtime import agent_workspaces
    monkeypatch.setattr(agent_workspaces, 'container_name', lambda role: 'selected-' + role)
    assert lifecycle._container_names() == ('selected-hermes', 'selected-openclaw')


def test_loaded_unhealthy_service_is_not_killed_by_start(monkeypatch, tmp_path):
    import jaeger_ai.features.gateway.service as gateway
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(lifecycle, '_get_launchd_jobs', lambda: {
        label: {'pid': 10, 'status': 0} for label, _, _ in lifecycle.SERVICES_ORDERED
    })
    monkeypatch.setattr(lifecycle, '_get_containers_state', lambda: {})
    monkeypatch.setattr(lifecycle, '_is_port_open', lambda *a, **kw: False)
    monkeypatch.setattr(lifecycle, '_service_port_open', lambda *a, **kw: False)
    monkeypatch.setattr(lifecycle.time, 'sleep', lambda _: None)
    monkeypatch.setattr(gateway, 'start', lambda: {'ok': True})
    calls = []
    monkeypatch.setattr(lifecycle.subprocess, 'run', lambda cmd, **kw: calls.append(cmd) or CompletedProcess(cmd, 0, '', ''))
    assert lifecycle._cmd_start_argv(['--no-app', '--no-containers']) == 1
    assert not any('bootout' in c for c in calls)


def test_failed_launchd_inspection_blocks_shutdown(monkeypatch):
    def failed():
        raise RuntimeError('Cannot inspect launchd')
    monkeypatch.setattr(lifecycle, '_get_launchd_jobs', failed)
    monkeypatch.setattr(lifecycle, '_get_containers_state', lambda: pytest.fail('must not proceed'))
    assert lifecycle._cmd_stop_argv(['--no-app']) == 1
