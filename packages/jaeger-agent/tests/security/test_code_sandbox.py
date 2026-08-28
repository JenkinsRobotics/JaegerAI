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
    monkeypatch.setattr(code, "_probe_linux_bwrap", lambda path: (True, ""))

    command, backend = code._sandboxed_python_command(
        str(script), workspace=str(workspace), scratch=str(scratch),
    )

    assert backend == "linux-bwrap"
    assert command is not None
    # The user namespace must be created before the network namespace so
    # bubblewrap owns it and can configure the isolated loopback device.
    assert command.index("--unshare-user") < command.index("--unshare-net")
    assert "--unshare-ipc" in command
    assert not any(
        command[index:index + 3] == ["--ro-bind", "/", "/"]
        for index in range(len(command) - 2)
    )
    assert ["--bind", str(workspace), str(workspace)] == command[
        command.index("--bind"):command.index("--bind") + 3
    ]


def test_linux_bwrap_policy_failure_is_fail_closed(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    scratch = tmp_path / "scratch"
    workspace.mkdir()
    scratch.mkdir()

    monkeypatch.setattr(code.sys, "platform", "linux")
    monkeypatch.setattr(code.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(
        code,
        "_probe_linux_bwrap",
        lambda path: (False, "loopback: operation not permitted"),
    )

    command, backend = code._sandboxed_python_command(
        str(workspace / "script.py"),
        workspace=str(workspace),
        scratch=str(scratch),
    )

    assert command is None
    assert backend.startswith("linux-bwrap-unavailable:")
    assert "operation not permitted" in backend
