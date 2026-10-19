"""A GUI-launched repository command must not import a stale installed wheel."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_source_launcher_binds_imports_from_an_external_working_directory(tmp_path):
    repo = Path(__file__).resolve().parents[4]
    venv = tmp_path / "probe-venv"
    (venv / "bin").mkdir(parents=True)
    interpreter = venv / "bin/python"
    interpreter.write_text(
        f"#!{sys.executable}\n"
        "import importlib.util,json,os\n"
        "print(json.dumps({'module':importlib.util.find_spec('jaeger_ai').origin,"
        "'install':os.environ.get('JAEGER_INSTALL_ROOT')}))\n"
    )
    interpreter.chmod(0o700)
    environment = {**os.environ, "JAEGER_VENV": str(venv)}
    environment.pop("PYTHONPATH", None)
    result = subprocess.run([str(repo / "jaeger"), "--version"], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert Path(payload["module"]) == repo / "jaeger_ai/__init__.py"
    assert payload["install"] == str(repo)
