"""Host inventory is cached and exposes only bounded read-only facts."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def test_capabilities_cached(monkeypatch):
    path = Path(__file__).resolve().parents[5] / 'jaeger_ai/features/webui/api/host_capabilities.py'
    spec = importlib.util.spec_from_file_location('host_capabilities_test', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []
    monkeypatch.setattr(mod, '_reachable', lambda url: calls.append(url) or True)
    monkeypatch.setattr(mod.shutil, 'which', lambda name: '/bin/' + name if name == 'node' else None)
    monkeypatch.setattr(mod.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(mod.platform, 'mac_ver', lambda: ('15.0', '', ''))
    command = lambda *args: 'Apple M4\n' if args[0] == 'sysctl' else 'Chipset Model: Apple M4\nMetal Support: Supported\n'
    snap = {'mem_total_gb': 32, 'mem_pressure': 1, 'disk_free_gb': 100, 'ollama_loaded': ['gemma:latest']}
    result = mod.capabilities(snap, command=command, clock=lambda: 10)
    assert result['cpu_model'] == 'Apple M4'
    assert result['gpu'] == 'Apple M4' and result['metal'] is True
    assert result['runtimes']['ollama']['loaded_models'] == ['gemma:latest']
    assert result['runtimes']['node']['present'] is True
    assert mod.capabilities({}, command=lambda *args: '', clock=lambda: 11) is result
    assert len(calls) == 3


def test_health_endpoint_uses_snapshot(monkeypatch):
    import sys
    from types import SimpleNamespace
    path = Path(__file__).resolve().parents[5] / 'jaeger_ai/features/webui/api/widgets_api.py'
    spec = importlib.util.spec_from_file_location('widgets_api_test', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fake_rm = SimpleNamespace(snapshot=lambda: {'mem_total_gb': 32})
    fake_host = SimpleNamespace(capabilities=lambda snap: {'memory_total_gb': snap['mem_total_gb']})
    monkeypatch.setitem(sys.modules, 'api', SimpleNamespace(unified_api=SimpleNamespace(_rm=lambda: fake_rm)))
    monkeypatch.setitem(sys.modules, 'api.host_capabilities', fake_host)
    payload = mod.machine_health()
    assert payload['capabilities']['memory_total_gb'] == 32
    assert payload['snapshot']['mem_total_gb'] == 32
