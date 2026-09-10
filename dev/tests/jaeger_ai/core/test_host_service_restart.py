"""Exercise the launcher effect without importing the live donor MCP runtime."""
import ast
from pathlib import Path
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[4]


def launcher_restart(monkeypatch, *, pending=None, response_status=200):
    tree = ast.parse((ROOT / 'scripts/run-host-capability-server.py').read_text())
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {
                '_RESTARTABLE_SERVICES', '_SERVICE_HEALTH_URLS'} for t in node.targets):
            selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == 'service_restart':
            node.decorator_list = []
            selected.append(node)
        elif isinstance(node, ast.Import) and any(alias.name == 'time' for alias in node.names):
            selected.append(node)
    calls, audit = [], []
    now = [0.]
    clock = SimpleNamespace(monotonic=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0]+seconds))
    class Response:
        status = response_status
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return b'{"status":"ok"}'
    def open_url(url, timeout):
        now[0] += timeout  # Include slow probes in the total time budget.
        if response_status != 200:
            raise urllib.error.HTTPError(url, response_status, 'unhealthy', {}, None)
        return Response()
    monkeypatch.setattr(urllib.request, 'urlopen', open_url)
    fake = SimpleNamespace(_audit=lambda *a, **kw: audit.append(kw), _authorize_effect=lambda *a, **kw: pending)
    namespace = {'host_capability_mcp_server': fake, 'urllib': urllib,
        'os': SimpleNamespace(getuid=lambda: 501),
        '_subprocess': SimpleNamespace(run=lambda *a, **kw: calls.append(a) or SimpleNamespace(returncode=0)),
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'launcher-service-restart', 'exec'), namespace)
    if 'time' in namespace:
        namespace['time'] = clock
    return namespace['service_restart'], calls, audit, now


def test_restart_waits_for_readiness_after_kick(monkeypatch):
    restart, calls, _, _ = launcher_restart(monkeypatch)
    result = restart('jaeger', 'one-shot-approval')
    assert calls and result['healthy'] is True


@pytest.mark.parametrize('status', [401, 404, 500, 503])
def test_restart_never_calls_an_http_error_healthy_and_has_a_real_deadline(monkeypatch, status):
    restart, calls, _, clock = launcher_restart(monkeypatch, response_status=status)
    result = restart('jaeger', 'one-shot-approval')
    assert calls and result['healthy'] is False
    assert clock[0] <= 30


def test_restart_does_not_execute_before_one_shot_approval(monkeypatch):
    pending = {'approval_required': True}
    restart, calls, _, _ = launcher_restart(monkeypatch, pending=pending)
    assert restart('jaeger') == pending
    assert calls == []


def test_restart_refuses_non_allowlisted_service(monkeypatch):
    restart, calls, _, _ = launcher_restart(monkeypatch)
    assert 'error' in restart('host-tools-gateway', 'approval')
    assert calls == []
