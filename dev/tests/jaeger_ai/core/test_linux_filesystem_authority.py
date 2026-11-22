"""Static Linux namespace proofs; never launch or modify a production process."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from jaeger_ai.core.authority import linux_filesystem as authority


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    executable = tmp_path / "bwrap"
    executable.touch()
    monkeypatch.setattr(authority.shutil, "which", lambda name: str(executable))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    command = [str(executable), "--die-with-parent", "--new-session",
               "--unshare-user", "--unshare-net", "--unshare-ipc",
               "--ro-bind", "/usr", "/usr", "--dev", "/dev",
               "--bind", str(workspace), str(workspace),
               "--remount-ro", "/", "--chdir", str(workspace),
               sys.executable, "-I", "-B", "-c", "print('fixture')"]
    return command, workspace


def restriction(path, deny_read=True):
    return SimpleNamespace(path=Path(path), deny_read=deny_read)


def test_isolated_workspace_preserves_existing_argv(sandbox, tmp_path):
    command, _ = sandbox
    assert authority.confine_existing_bwrap(command, [restriction(tmp_path / "home/.codex/sessions")]) == command


def test_current_execute_code_producer_is_accepted(sandbox, monkeypatch, tmp_path):
    from jaeger_agent.tools import code

    _, workspace = sandbox
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(code.sys, "platform", "linux")
    monkeypatch.setattr(code, "_probe_linux_bwrap", lambda path: (True, ""))
    command, backend = code._sandboxed_python_command(
        str(scratch / "fixture.py"), workspace=str(workspace), scratch=str(scratch),
    )
    assert backend == "linux-bwrap"
    assert authority.confine_existing_bwrap(command, [restriction(tmp_path / "home/.codex/sessions")]) == command


@pytest.mark.parametrize("relative", [".", "nested", "../workspace"])
def test_writable_mount_cannot_overlap_protected_data(sandbox, relative):
    command, workspace = sandbox
    with pytest.raises(PermissionError, match="overlaps protected"):
        authority.confine_existing_bwrap(command, [restriction(workspace / relative, deny_read=False)])


@pytest.mark.parametrize("mode", ["--bind", "--ro-bind"])
@pytest.mark.parametrize("side", [0, 1])
def test_source_and_destination_cannot_expose_protected_home(sandbox, tmp_path, mode, side):
    command, _ = sandbox
    pos = command.index("--bind")
    command[pos] = mode
    command[pos + 1 + side] = str(tmp_path / "home")
    with pytest.raises(PermissionError, match="overlaps protected"):
        authority.confine_existing_bwrap(command, [restriction(tmp_path / "home/.codex/memories")])


def test_read_only_mount_can_cover_write_only_restriction(sandbox):
    command, workspace = sandbox
    command[command.index("--bind")] = "--ro-bind"
    assert authority.confine_existing_bwrap(command, [restriction(workspace / "memory.md", False)]) == command


def test_symlink_source_alias_is_checked(sandbox, tmp_path):
    command, workspace = sandbox
    protected = tmp_path / "protected"
    protected.mkdir()
    alias = workspace / "alias"
    alias.symlink_to(protected, target_is_directory=True)
    command[command.index("--bind") + 1] = str(alias)
    with pytest.raises(PermissionError, match="overlaps protected"):
        authority.confine_existing_bwrap(command, [restriction(protected)])


@pytest.mark.parametrize("change", ["root", "unknown", "missing_namespace", "unfrozen", "late_mount", "shell", "wrong_binary"])
def test_unproven_sandboxes_fail_closed(sandbox, change):
    command, _ = sandbox
    if change == "root":
        pos = command.index("--ro-bind")
        command[pos + 1:pos + 3] = ["/", "/"]
    elif change == "unknown":
        command[1:1] = ["--share-net"]
    elif change == "missing_namespace":
        command.remove("--unshare-net")
    elif change == "unfrozen":
        pos = command.index("--remount-ro")
        del command[pos:pos + 2]
    elif change == "late_mount":
        pos = command.index("--chdir")
        command[pos:pos] = ["--bind", "/tmp", "/tmp"]
    elif change == "shell":
        command[-5:] = ["/bin/sh", "-c", "true"]
    else:
        command[0] = "/bin/sh"
    with pytest.raises(PermissionError):
        authority.confine_existing_bwrap(command, [])


def test_arbitrary_shell_is_not_treated_as_isolated(sandbox):
    with pytest.raises(PermissionError, match="only the existing"):
        authority.confine_existing_bwrap(["/bin/sh", "-c", "true"], [])
