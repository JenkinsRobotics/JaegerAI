"""Read-only, cached host capability inventory for the Machine tab."""
from __future__ import annotations

import os
import platform
import shutil
import time
import urllib.request
from pathlib import Path

_cache: tuple[float, dict] | None = None


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.4) as response:
            return response.status < 500
    except (OSError, ValueError):
        return False


def capabilities(snapshot: dict, command=None, clock=time.monotonic) -> dict:
    global _cache
    now = clock()
    if _cache and now - _cache[0] < 5:
        return _cache[1]
    if command is None:
        from api.resource_manager import _out  # type: ignore
        command = lambda *args: _out(list(args), timeout=1)
    cpu = command('sysctl', '-n', 'machdep.cpu.brand_string').strip() or None
    display = command('system_profiler', 'SPDisplaysDataType')
    gpu = next((line.split(':', 1)[1].strip() for line in display.splitlines() if 'Chipset Model:' in line), None)
    runtime = {name: {'present': bool(shutil.which(name)), 'reachable': None}
               for name in ('docker', 'colima', 'node', 'hermes', 'openclaw')}
    venv = os.environ.get('VIRTUAL_ENV')
    runtime['python_venv'] = {'present': bool(venv and Path(venv).is_dir()), 'reachable': None}
    runtime['ollama'] = {'present': bool(shutil.which('ollama')),
                         'reachable': _reachable('http://127.0.0.1:11434/api/version'),
                         'loaded_models': snapshot.get('ollama_loaded') or []}
    runtime['gateway'] = {'present': True, 'reachable': _reachable('http://127.0.0.1:33418/health')}
    runtime['hub'] = {'present': True, 'reachable': _reachable('http://127.0.0.1:8792/health')}
    result = {'cpu_model': cpu, 'cpu_cores': os.cpu_count(),
              'memory_total_gb': snapshot.get('mem_total_gb'), 'memory_pressure': snapshot.get('mem_pressure'),
              'gpu': gpu, 'neural_engine': platform.machine() == 'arm64' if cpu else None,
              'metal': 'Supported' in display if display else None,
              'disk_free_gb': snapshot.get('disk_free_gb'), 'macos_version': platform.mac_ver()[0] or None,
              'runtimes': runtime}
    _cache = (now, result)
    return result
