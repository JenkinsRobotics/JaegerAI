from __future__ import annotations

from jaeger_ai.core.runtime.fabric_supervisor import (
    FAILURE_THRESHOLD,
    REPAIR_COOLDOWN_S,
    Component,
    Supervisor,
    JAEGER_RUNTIME_ROOT,
    REPO_ROOT,
    _state_path,
)


def test_supervisor_state_lives_inside_repository():
    import os
    from pathlib import Path
    assert JAEGER_RUNTIME_ROOT == Path(os.environ["JAEGER_HOME"]) / "shared"
    assert _state_path() == JAEGER_RUNTIME_ROOT / "health" / "agent-fabric.json"


def test_container_probe_discovers_address_after_restart(monkeypatch):
    import json
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    monkeypatch.setattr(supervisor.subprocess, "check_output", lambda *args, **kwargs:
        json.dumps([{"status": {"state": "running", "networks": [{"ipv4Address": "192.168.64.99/24"}]}}]).encode())
    urls = []
    monkeypatch.setattr(supervisor, "_http", lambda url: urls.append(url) or True)
    assert supervisor._container_http("hermes-webui-hermes-webui", 8787)
    assert urls == ["http://192.168.64.99:8787/health"]


def test_repair_requires_repeated_failure_and_preserves_healthy_component():
    repairs: list[str] = []
    broken = Component("broken", lambda: False, lambda: not repairs.append("broken"))
    healthy = Component("healthy", lambda: True, lambda: not repairs.append("healthy"))
    supervisor = Supervisor((broken, healthy))

    for tick in range(FAILURE_THRESHOLD - 1):
        status = supervisor.tick(now=1000 + tick)
        assert status["broken"]["repair_attempted"] is False
    status = supervisor.tick(now=1000 + FAILURE_THRESHOLD)

    assert status["broken"]["repair_command_ok"] is True
    assert status["broken"]["repair_ok"] is False
    assert status["broken"]["consecutive_failures"] >= FAILURE_THRESHOLD
    assert repairs == ["broken"]


def test_repair_cooldown_prevents_restart_loop():
    repairs: list[int] = []
    component = Component("x", lambda: False, lambda: not repairs.append(1))
    supervisor = Supervisor((component,))

    for _ in range(FAILURE_THRESHOLD):
        supervisor.tick(now=1000)
    for _ in range(FAILURE_THRESHOLD):
        supervisor.tick(now=1000 + REPAIR_COOLDOWN_S - 1)

    assert len(repairs) == 1


def test_repair_success_requires_readiness_and_updates_health():
    ready = [False]
    def repair():
        ready[0] = True
        return True
    supervisor = Supervisor((Component('x', lambda: ready[0], repair),))
    for _ in range(FAILURE_THRESHOLD):
        status = supervisor.tick(now=1000)
    assert status['x']['healthy'] is True
    assert status['x']['repair_ok'] is True
    assert status['x']['consecutive_failures'] == 0


def test_broken_probe_and_repair_do_not_stop_other_components():
    def broken(): raise RuntimeError('private details')
    supervisor = Supervisor((Component('bad', broken, broken), Component('good', lambda: True, broken)))
    for _ in range(FAILURE_THRESHOLD):
        status = supervisor.tick(now=1000)
    assert status['good']['healthy']
    assert status['bad']['repair_ok'] is False
    assert 'private details' not in str(status)


def test_container_restart_refuses_unknown_state_and_has_bounded_inspection(monkeypatch):
    import subprocess
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    def timeout(*args, **kwargs):
        assert kwargs['timeout'] <= 5
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
    monkeypatch.setattr(supervisor.subprocess, 'check_output', timeout)
    monkeypatch.setattr(supervisor, '_run', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('must not restart')))
    assert supervisor._restart_container('jaeger-hermes-webui') is False


def test_running_container_is_not_blindly_restarted(monkeypatch):
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    monkeypatch.setattr(supervisor.subprocess, 'check_output', lambda *a, **kw: b'[{"status":{"state":"running"}}]')
    calls = []
    monkeypatch.setattr(supervisor, '_run', lambda command, **kw: calls.append(command) or False)
    assert supervisor._restart_container('jaeger-hermes-webui') is False
    assert calls == []


def test_stopped_container_can_be_started_without_deleting_state(monkeypatch):
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    monkeypatch.setattr(supervisor.subprocess, 'check_output', lambda *a, **kw: b'[{"status":{"state":"stopped"}}]')
    calls = []
    monkeypatch.setattr(supervisor, '_run', lambda command, **kw: calls.append(command) or True)
    assert supervisor._restart_container('jaeger-hermes-webui') is True
    assert calls == [['/opt/homebrew/bin/container', 'start', 'jaeger-hermes-webui']]


def test_explicit_repair_exits_unsuccessfully_when_not_ready(monkeypatch):
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    monkeypatch.setattr(supervisor, 'components', lambda: (Component('jaeger', lambda: False, lambda: True),))
    saved = []
    monkeypatch.setattr(supervisor, 'write_state', saved.append)
    assert supervisor.main(['--repair', 'jaeger']) == 1
    assert saved[0]['jaeger']['repair_command_ok'] is True
    assert saved[0]['jaeger']['repair_ok'] is False


def test_rack_is_optional_and_mac_ollama_is_the_default(monkeypatch):
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    monkeypatch.delenv('JAEGER_RACK_SERVICES', raising=False)
    names = [item.name for item in supervisor.components()]
    assert 'ollama' in names and 'honcho' not in names
    monkeypatch.setenv('JAEGER_RACK_SERVICES', 'true')
    assert 'honcho' in [item.name for item in supervisor.components()]


def test_explicit_honcho_repair_is_unavailable_while_rack_is_paused(monkeypatch):
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    monkeypatch.delenv('JAEGER_RACK_SERVICES', raising=False)
    assert supervisor.main(['--repair', 'honcho']) == 2


def test_degraded_running_gateway_is_not_blindly_stopped(monkeypatch):
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    import jaeger_ai.features.gateway.service as gateway_service
    monkeypatch.setattr(gateway_service, 'status', lambda: {'running': True})
    monkeypatch.setattr(supervisor, '_tcp', lambda *a, **kw: False)
    monkeypatch.setattr(gateway_service, 'start', lambda: (_ for _ in ()).throw(AssertionError('must not restart')))
    assert supervisor._start_jaeger_gateway() is False


def test_jaeger_repair_restores_bridge_backend_adapter_and_owned_gateway(monkeypatch):
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    calls = []
    monkeypatch.setattr(supervisor, '_bridge_ready', lambda: False)
    monkeypatch.setattr(supervisor, '_tcp', lambda *a: False)
    monkeypatch.setattr(supervisor, '_http', lambda *a: False)
    monkeypatch.setattr(supervisor, '_kickstart', lambda label: calls.append(label) or True)
    monkeypatch.setattr(supervisor, '_start_jaeger_gateway', lambda: calls.append('owned-gateway') or True)
    assert supervisor._repair_jaeger()
    assert calls == [
        'com.jenkinsrobotics.jaeger-bridge',
        'com.jenkinsrobotics.jaeger-mcp-http',
        'com.jenkinsrobotics.jaeger-hermes-adapter',
        'owned-gateway',
    ]


def test_a2a_health_requires_backend_and_public_gateway(monkeypatch):
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    requested = []
    monkeypatch.setattr(supervisor, '_http', lambda url: requested.append(url) or '8812' not in url)
    a2a = next(item for item in supervisor.components() if item.name == 'a2a')
    assert not a2a.probe()
    assert requested == [
        'http://127.0.0.1:8796/.well-known/agent-card.json',
        'http://127.0.0.1:8812/.well-known/agent-card.json',
    ]


def test_jaeger_health_checks_the_actual_mcp_listener_not_a_nonexistent_health_route(monkeypatch):
    from jaeger_ai.core.runtime import fabric_supervisor as supervisor
    urls, ports = [], []
    monkeypatch.setattr(supervisor, '_bridge_ready', lambda: True)
    monkeypatch.setattr(supervisor, '_http', lambda url: urls.append(url) or True)
    monkeypatch.setattr(supervisor, '_tcp', lambda host, port: ports.append(port) or True)
    jaeger = next(item for item in supervisor.components() if item.name == 'jaeger')
    assert jaeger.probe()
    assert urls == ['http://192.168.64.1:8642/v1/health']
    assert ports == [8792, 8811]
