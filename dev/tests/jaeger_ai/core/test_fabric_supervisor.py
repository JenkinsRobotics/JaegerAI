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

    assert status["broken"]["repair_ok"] is True
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
