"""Exercise the shell runner's pre-collection isolation with a harmless pytest stub."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.subprocess
REPO = Path(__file__).resolve().parents[4]


def test_offline_runner_replaces_inherited_live_state(tmp_path):
    bin_dir = tmp_path / ".jaeger" / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "pytest"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "if '--help' in sys.argv: sys.exit(0)\n"
        "print(json.dumps({k: v for k, v in os.environ.items() "
        "if k.startswith(('JAEGER_', 'HERMES_'))}))\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    environment = {
        **os.environ,
        "HOME": str(tmp_path),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "JAEGER_STATE_DIR": str(tmp_path / "operator-live-state"),
        "JAEGER_HOME": str(tmp_path / "operator-home"),
        "JAEGER_INSTANCE_DIR": str(tmp_path / "operator-instance"),
        "JAEGER_ACCEPTANCE": "1",
        "HERMES_HOME": str(tmp_path / "operator-hermes"),
        "HERMES_WEBUI_STATE_DIR": str(tmp_path / "operator-webui"),
    }
    result = subprocess.run(
        ["bash", str(REPO / "dev/scripts/run_tests.sh"), "--unit"],
        env=environment, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    for key in ("JAEGER_STATE_DIR", "JAEGER_INSTANCE_DIR", "JAEGER_ACCEPTANCE"):
        assert key not in observed
    state = Path(observed["JAEGER_HOME"])
    assert state.is_dir()
    assert state.name.startswith("jaeger-test-run.")
    assert not state.is_relative_to(REPO)
    assert observed["HERMES_HOME"] == str(state / "hermes")
    assert observed["HERMES_WEBUI_STATE_DIR"] == str(state / "webui")
    assert observed["HERMES_WEBUI_DEFAULT_WORKSPACE"] == str(state / "workspace")
    # Stub never imports the application: the only artifact is the empty root.
    assert list(state.iterdir()) == []
    state.rmdir()
