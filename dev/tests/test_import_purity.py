"""Import purity in a fresh process (Q01; RELEASE_AGENT_PROMPT.md section 12).

"Imports create no files, databases, threads, servers, migrations or live
tool registrations. Test in fresh processes with denied writes/network."

Every module of the listed packages is imported in a clean interpreter
whose HOME and working directory are empty temporary directories. The test
fails if any import prints to stdout or creates anything under either.

Regression: ``jaeger_agent/tools/safari.py`` — a one-off script swept into
the shipped tool package — read ~/Library/Safari/Bookmarks.plist, printed
the operator's bookmarks and wrote an index file *at import time*.

A module that cannot import for a missing optional dependency is reported,
not failed: availability is the catalog's concern, purity is this test's.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGES = [
    "jaeger_agent.tools",
    "jaeger_os.core.tools",
    "jaeger_ai.core.instance",
    "jaeger_ai.core.gateway",
    "jaeger_ai.core.runtime.cancellation",
]

_PROBE = r"""
import importlib, json, pkgutil, sys, io, contextlib
printed = {}   # module -> byte count; content is never reported (it may be private)
failed = {}

def load(name):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            failed[name] = type(exc).__name__
            module = None
    if buffer.getvalue():
        printed[name] = len(buffer.getvalue())
    return module

for root in json.loads(sys.argv[1]):
    mod = load(root)
    if mod is None:
        continue
    for info in pkgutil.walk_packages(getattr(mod, "__path__", []), root + "."):
        load(info.name)
print(json.dumps({"printed": printed, "failed": failed}))
"""


def test_importing_tool_and_core_surfaces_has_no_side_effects(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join([
            str(REPO / "packages/jaeger-agent"), str(REPO / "packages/jaeger-os"), str(REPO),
        ]),
        "JAEGER_STATE_DIR": str(tmp_path / "state"),
        "JAEGER_NO_ATTACH": "1",
        "JAEGER_NO_GUI": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, json.dumps(PACKAGES)],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])

    assert report["printed"] == {}, f"modules printed at import (bytes): {report['printed']}"
    created = sorted(str(p.relative_to(tmp_path)) for p in (*home.rglob("*"), *cwd.rglob("*")))
    assert created == [], f"imports created files: {created[:20]}"
    state = tmp_path / "state"
    assert not state.exists() or not any(state.rglob("*")), "imports wrote operator state"


def test_the_bookmark_scraping_script_is_not_shipped():
    assert not (REPO / "packages/jaeger-agent/jaeger_agent/tools/safari.py").exists()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
