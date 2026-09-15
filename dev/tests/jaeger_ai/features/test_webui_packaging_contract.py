from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SUPERVISOR = ROOT / "integrations/hermes_webui/jaeger_sidecar_supervisor.py"


def _load_supervisor():
    spec = importlib.util.spec_from_file_location("jaeger_sidecar_supervisor", SUPERVISOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_prepare_produces_versioned_complete_overlay():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/prepare-hermes-webui.py")],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    staged = Path(result.stdout.strip().splitlines()[-1])
    version_source = (staged / "api/_version.py").read_text(encoding="utf-8")
    assert "unknown" not in version_source
    assert re.search(r"exp-v0\.52\.264-\d+-g[0-9a-f]+", version_source)
    assert (staged / "jaeger-extensions/jaeger_stream_continuity.js").is_file()
    assert (staged / "jaeger_sidecar_supervisor.py").is_file()
    init = (staged / "docker_init.bash").read_text(encoding="utf-8")
    assert "jaeger_sidecar_supervisor.py" in init


def test_dispatcher_supervisor_restarts_after_repeated_health_failures():
    module = _load_supervisor()
    children = []
    probes = iter([False, False, False, True])

    class Child:
        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    def spawn():
        child = Child()
        children.append(child)
        return child

    module.run(
        stop_requested=lambda: len(children) == 2,
        health_check=lambda: next(probes),
        spawn=spawn,
        sleep=lambda _seconds: None,
    )

    assert len(children) == 2
    assert children[0].terminated is True
    assert children[1].terminated is True
