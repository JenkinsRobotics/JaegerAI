"""Linux code execution must construct a usable, network-isolated sandbox."""

from __future__ import annotations

from pathlib import Path

from jaeger_agent.tools import code


def test_linux_bwrap_owns_network_namespace(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    scratch = tmp_path / "scratch"
    workspace.mkdir()
    scratch.mkdir()
    script = workspace / "script.py"
    script.write_text("print(42)\n", encoding="utf-8")

    monkeypatch.setattr(code.sys, "platform", "linux")
    monkeypatch.setattr(code.shutil, "which", lambda name: "/usr/bin/bwrap")

    command, backend = code._sandboxed_python_command(
        str(script), workspace=str(workspace), scratch=str(scratch),
    )

    assert backend == "linux-bwrap"
    assert command is not None
    # The user namespace must be created before the network namespace so
    # bubblewrap owns it and can configure the isolated loopback device.
    assert command.index("--unshare-user") < command.index("--unshare-net")
    assert "--unshare-ipc" in command
