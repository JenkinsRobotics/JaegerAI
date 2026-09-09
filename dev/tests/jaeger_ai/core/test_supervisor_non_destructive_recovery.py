"""Health failures must not kill work still owned by a native process."""
import subprocess

from jaeger_ai.core.runtime import fabric_supervisor as supervisor


def test_live_worker_is_preserved(monkeypatch):
    monkeypatch.setattr(supervisor.subprocess, 'run', lambda *a, **kw:
        subprocess.CompletedProcess(a[0], 0, 'service = {\n\tpid = 123\n}', ''))
    calls = []
    monkeypatch.setattr(supervisor, '_run', lambda cmd: calls.append(cmd) or True)
    assert supervisor._kickstart('test-worker') is False
    assert calls == []


def test_exited_loaded_worker_can_start_without_force(monkeypatch):
    monkeypatch.setattr(supervisor.subprocess, 'run', lambda *a, **kw:
        subprocess.CompletedProcess(a[0], 0, 'state = not running', ''))
    calls = []
    monkeypatch.setattr(supervisor, '_run', lambda cmd: calls.append(cmd) or True)
    assert supervisor._kickstart('test-worker') is True
    assert calls[0][1] == 'kickstart'
    assert '-k' not in calls[0]


def test_inspection_failure_does_not_start_or_restart(monkeypatch):
    monkeypatch.setattr(supervisor.subprocess, 'run', lambda *a, **kw:
        subprocess.CompletedProcess(a[0], 1, '', 'Permission denied'))
    calls = []
    monkeypatch.setattr(supervisor, '_run', lambda cmd: calls.append(cmd) or True)
    assert supervisor._kickstart('test-worker') is False
    assert calls == []


def test_repair_only_touches_failed_dependency(monkeypatch):
    monkeypatch.setattr(supervisor, '_bridge_ready', lambda: True)
    monkeypatch.setattr(supervisor, '_tcp', lambda *a: False)
    monkeypatch.setattr(supervisor, '_http', lambda *a: True)
    monkeypatch.setattr(supervisor, '_start_jaeger_gateway', lambda: True)
    calls = []
    monkeypatch.setattr(supervisor, '_kickstart', lambda label: calls.append(label) or True)
    assert supervisor._repair_jaeger() is True
    assert calls == ['com.jenkinsrobotics.jaeger-mcp-http']


def test_openclaw_adapter_can_recover_without_restarting_native_container(monkeypatch):
    monkeypatch.setattr(supervisor, '_tcp', lambda *a: True)
    monkeypatch.setattr(supervisor, '_http', lambda *a: False)
    calls = []
    monkeypatch.setattr(supervisor, '_kickstart', lambda label: calls.append(label) or True)
    monkeypatch.setattr(supervisor, '_restart_container', lambda name: (_ for _ in ()).throw(AssertionError('native is healthy')))
    assert supervisor._repair_openclaw()
    assert calls == ['com.jenkinsrobotics.openclaw-hermes-adapter']


def test_a2a_gateway_recovers_without_restarting_healthy_backend(monkeypatch):
    monkeypatch.setattr(supervisor, '_http', lambda *a: True)
    monkeypatch.setattr(supervisor, '_kickstart', lambda label: (_ for _ in ()).throw(AssertionError('backend is healthy')))
    monkeypatch.setattr(supervisor, '_start_jaeger_gateway', lambda: True)
    assert supervisor._repair_a2a()
