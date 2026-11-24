"""SandboxPort contract tests + LIVE macOS sandbox-exec runtime verification."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from jaeger_authority import (
    ContainerSandbox,
    LinuxBwrapSandbox,
    MacOsSeatbeltSandbox,
    UnconfinedSandbox,
)
from jaeger_contracts import SandboxPort, SandboxProfile


def test_all_sandbox_backends_satisfy_sandbox_port(tmp_path: Path) -> None:
    backends = {
        "seatbelt": MacOsSeatbeltSandbox(),
        "bwrap": LinuxBwrapSandbox(),
        "docker": ContainerSandbox(cli="docker"),
        "unconfined": UnconfinedSandbox(),
    }
    profile = SandboxProfile(workspace=tmp_path, allow_network=False)
    for impl_id, sb in backends.items():
        assert isinstance(sb, SandboxPort)
        spec = sb.prepare(["echo", "ok"], profile)
        assert spec.argv
        if impl_id != "unconfined":
            assert spec.read_only_default is True
            assert spec.protects_workspace_boundary is True
            assert spec.protects_git_metadata is True
            assert spec.protects_secret_stores is True


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt live test")
def test_macos_seatbelt_live_execution_and_confinement(tmp_path: Path) -> None:
    """Runs REAL commands under /usr/bin/sandbox-exec if not already nested in Seatbelt."""
    ws = tmp_path / "workspace"
    (ws / ".git" / "hooks").mkdir(parents=True)
    hook = ws / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_secret = outside_dir / "secret.txt"
    outside_secret.write_text("TOP_SECRET_VALUE")

    # Note: tmp_path is under /tmp or /var/folders; disable allow_tmp_writes so
    # ONLY `ws` is writable and `outside_dir` is strictly read-only!
    profile = SandboxProfile(
        workspace=ws,
        denied_read_paths=(outside_secret,),
        allow_network=False,
        allow_tmp_writes=False,
    )
    sb = MacOsSeatbeltSandbox()

    # Probe if nested sandbox-exec is permitted in this test harness
    probe = subprocess.run(
        sb.prepare(["/usr/bin/true"], profile).argv,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if probe.returncode != 0 and "sandbox_apply" in (probe.stderr or "").lower():
        pytest.skip(f"Host harness already inside nested Seatbelt: {probe.stderr.strip()}")

    assert probe.returncode == 0, f"Seatbelt base policy failed to run /usr/bin/true: {probe.stderr}"

    # 1. Real Python execution + writing inside workspace MUST SUCCEED
    # 2. Writing outside workspace MUST FAIL with PermissionError
    # 3. Writing to .git/hooks/pre-commit MUST FAIL with PermissionError
    # 4. Reading denied secret path MUST FAIL with PermissionError
    script = f"""
import pathlib
ws_file = pathlib.Path({str(ws / 'hello.txt')!r})
ws_file.write_text('INSIDE_OK')
print('WS_WRITE:' + ws_file.read_text())

try:
    pathlib.Path({str(outside_dir / 'escaped.txt')!r}).write_text('BAD')
    print('OUTSIDE_WRITE:ESCAPED')
except PermissionError:
    print('OUTSIDE_WRITE:BLOCKED')

try:
    pathlib.Path({str(hook)!r}).write_text('PWN')
    print('GIT_HOOK:ESCAPED')
except PermissionError:
    print('GIT_HOOK:BLOCKED')

try:
    pathlib.Path({str(outside_secret)!r}).read_text()
    print('SECRET_READ:ESCAPED')
except PermissionError:
    print('SECRET_READ:BLOCKED')
"""
    spec = sb.prepare([sys.executable, "-B", "-c", script], profile)
    res = subprocess.run(spec.argv, capture_output=True, text=True, timeout=15)
    assert res.returncode == 0, f"Python failed inside Seatbelt: {res.stderr}"
    assert res.stdout.splitlines() == [
        "WS_WRITE:INSIDE_OK",
        "OUTSIDE_WRITE:BLOCKED",
        "GIT_HOOK:BLOCKED",
        "SECRET_READ:BLOCKED",
    ]
    assert (ws / "hello.txt").read_text() == "INSIDE_OK"
    assert not (outside_dir / "escaped.txt").exists()
    assert hook.read_text() == "#!/bin/sh\nexit 0\n"
