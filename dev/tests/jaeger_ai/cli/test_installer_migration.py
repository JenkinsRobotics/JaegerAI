"""Release-installer contract for the 0.9 ``~/jaeger`` → 0.12 migration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[4]
INSTALLER = REPO / "scripts" / "install.sh"


def _fake_commands(tmp_path: Path) -> Path:
    """Provide a local git clone that creates the minimum product checkout."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    git = fakebin / "git"
    git.write_text(
        "#!/bin/bash\n"
        "set -eu\n"
        "if [[ \"${1:-}\" == clone ]]; then\n"
        "  target=\"${@: -2:1}\"\n"
        "  mkdir -p \"$target/.git\"\n"
        "  printf '#!/bin/bash\\nexit 0\\n' > \"$target/install.sh\"\n"
        "  chmod +x \"$target/install.sh\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    (fakebin / "python3.12").symlink_to(sys.executable)
    return fakebin


def _env(tmp_path: Path, fakebin: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("JAEGER_HOME", None)
    env["HOME"] = str(tmp_path)
    env["JAEGER_REPO_URL"] = "https://example.invalid/JaegerAI.git"
    env["PATH"] = os.pathsep.join((str(fakebin), env.get("PATH", "")))
    return env


def _legacy_state(tmp_path: Path) -> Path:
    state = tmp_path / "jaeger" / ".jaeger_os"
    memory = state / "instances" / "lilith" / "memory"
    memory.mkdir(parents=True)
    (memory / "memory.db").write_bytes(b"operator-memory")
    (state / "active_instance").write_text("lilith\n", encoding="utf-8")
    return state


def test_product_installer_migrates_legacy_state_and_keeps_source(tmp_path):
    old_state = _legacy_state(tmp_path)
    fakebin = _fake_commands(tmp_path)

    result = subprocess.run(
        ["bash", str(INSTALLER)],
        env=_env(tmp_path, fakebin),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    new_state = tmp_path / "JaegerAI" / ".jaeger_os"
    assert (new_state / "active_instance").read_text() == "lilith\n"
    assert (new_state / "instances/lilith/memory/memory.db").read_bytes() == b"operator-memory"
    assert (new_state / ".migrated-from").read_text().strip() == str(tmp_path / "jaeger")
    assert old_state.is_dir(), "legacy state is the rollback copy and must remain"


@pytest.mark.parametrize("large_process_table", [False, True])
def test_product_installer_refuses_to_copy_running_legacy_install(tmp_path, large_process_table):
    _legacy_state(tmp_path)
    fakebin = _fake_commands(tmp_path)
    if large_process_table:
        fake_ps = fakebin / "ps"
        fake_ps.write_text(
            '#!/bin/bash\n'
            'printf "123 %s/jaeger/running-agent\\n" "$HOME"\n'
            'for ((i=0; i<20000; i++)); do\n'
            '  printf "456 /usr/bin/unrelated-process\\n"\n'
            'done\n'
        )
        fake_ps.chmod(0o755)
    running = tmp_path / "jaeger" / "running-agent"
    running.symlink_to("/bin/sleep")
    process = subprocess.Popen([str(running), "30"])
    try:
        result = subprocess.run(
            ["bash", str(INSTALLER)],
            env=_env(tmp_path, fakebin),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            check=False,
        )
    finally:
        process.terminate()
        process.wait(timeout=5)

    assert result.returncode == 1
    assert "still running" in result.stdout
    assert not (tmp_path / "JaegerAI").exists()
