"""Resource restrictions shared by local file tools and child processes.

Framework grants govern data, not just the name of the connector tool. The
resource inventory comes from framework discovery; shell command text is never
parsed to decide whether a process can read it. On macOS Seatbelt enforces the
same denied paths in the child and its descendants. This is a filesystem
boundary, not isolation from already running services or remote machines.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from jaeger_ai.core.frameworks.discovery import KNOWN
from jaeger_ai.core.frameworks.grants import FrameworkGrants


@dataclass(frozen=True)
class RestrictedPath:
    path: Path
    reason: str
    deny_read: bool = True


def restricted_paths() -> tuple[RestrictedPath, ...]:
    """Re-evaluate owner grants at each access/spawn; never cache revocations.

    A glob's literal prefix is the smallest stable subtree we can protect
    without enumerating current files (which would miss future writes). Where
    session and memory globs share a subtree, raw access needs both grants;
    a connector can still read its narrower granted collection.
    """
    home = Path(os.environ.get("JAEGER_FRAMEWORK_HOME") or Path.home()).expanduser()
    grants = FrameworkGrants()
    configured = grants.all()
    restrictions: dict[Path, RestrictedPath] = {}
    for framework in KNOWN:
        if not framework.readable:
            continue
        for capability, patterns in (("read_sessions", framework.sessions),
                                     ("read_memory", framework.memory)):
            granted = ((configured.get(framework.id) or {}).get(capability) or {}).get("granted") is True
            for root in framework.roots:
                for pattern in patterns:
                    literal = []
                    for part in Path(pattern).parts:
                        if any(char in part for char in "*?["):
                            break
                        literal.append(part)
                    path = home.joinpath(root, *literal)
                    reason = (f"The owner has not granted {capability} for framework "
                              f"{framework.id!r}. This applies to file and process access too; "
                              "do not retry through another tool.")
                    if granted:
                        reason = "Other frameworks' history and memory are read-only; a read grant cannot authorize writes."
                    # Keep lexical and resolved locations. A symlink to a store
                    # must not change its authority; a later replacement at the
                    # lexical location must remain restricted as well.
                    for location in (path.absolute(), path.resolve()):
                        previous = restrictions.get(location)
                        if previous is None or not previous.deny_read:
                            restrictions[location] = RestrictedPath(location, reason, deny_read=not granted)
    # An agent may not manufacture its own grants through a file/shell tool.
    for path in (grants.path, grants.audit_path):
        reason = "Framework authority records are owner-managed; use the Frameworks controls."
        restrictions[path.absolute()] = RestrictedPath(path.absolute(), reason)
        restrictions[path.resolve()] = RestrictedPath(path.resolve(), reason)
    return tuple(value for _, value in sorted(restrictions.items()))


def check_path(path: Path | str, *, write: bool = False) -> None:
    """Reject direct access to denied resources, including symlink aliases."""
    path_guard()(path, write=write)


def path_guard():
    """One short-lived policy snapshot for a bounded recursive file operation."""
    restrictions = restricted_paths()

    def check(path: Path | str, *, write: bool = False) -> None:
        target = Path(path).expanduser().resolve()
        for restriction in restrictions:
            if not write and not restriction.deny_read:
                continue
            if target == restriction.path or restriction.path in target.parents:
                raise PermissionError(restriction.reason)

    return check


def confine_command(
    command: Sequence[str],
    *,
    workspace: Path | str | None = None,
    allow_network: bool | None = None,
) -> list[str]:
    """Install OS kernel confinement before exec; never fall back unconfined.

    When ``workspace`` is supplied on macOS, delegates directly to standalone
    ``jaeger_authority.MacOsSeatbeltSandbox`` (read-only-by-default outside the
    workspace, `.git` write-locked, secret stores + framework restricted paths
    denied, `~/.jaeger/venv` preserved read-only for canonical venv execution).
    """
    denied = tuple(replace(item, deny_read=True) for item in restricted_paths())
    command = list(command)
    if sys.platform == "linux":
        if not denied:
            return command
        from .linux_filesystem import confine_existing_bwrap
        return confine_existing_bwrap(command, denied)

    sandbox = Path("/usr/bin/sandbox-exec")
    if sys.platform != "darwin" or not sandbox.is_file():
        if not denied and workspace is None:
            return command
        raise PermissionError("Filesystem authority requires a supported OS sandbox; "
                              "unconfined process execution is refused.")

    # Existing default-deny sandbox-exec command (e.g. execute_code): append denials only
    if command and command[0] == str(sandbox) and "-p" in command:
        if not denied:
            return command
        extra: list[str] = []
        for restriction in denied:
            literal = json.dumps(str(restriction.path), ensure_ascii=True)
            operations = "file-read* file-write*" if restriction.deny_read else "file-write*"
            extra.append(f"(deny {operations} (subpath {literal}))")
            for ancestor in restriction.path.parents:
                if ancestor == Path("/"):
                    break
                extra.append(f"(deny file-write-unlink (literal {json.dumps(str(ancestor))}))")
        index = command.index("-p") + 1
        if index >= len(command):
            raise ValueError("Sandbox command is missing its profile")
        command[index] += "\n" + "\n".join(dict.fromkeys(extra))
        return command

    # Workspace-scoped production subprocesses: enforce read-only-default Seatbelt via jaeger-authority!
    if workspace is not None:
        from jaeger_authority import MacOsSeatbeltSandbox
        from jaeger_contracts import SandboxProfile

        net = (
            allow_network
            if allow_network is not None
            else os.environ.get("JAEGER_SANDBOX_ALLOW_NETWORK", "0").strip() == "1"
        )
        profile = SandboxProfile(
            workspace=Path(workspace),
            denied_read_paths=tuple(r.path for r in denied if r.deny_read),
            denied_write_paths=tuple(r.path for r in denied),
            allow_network=net,
        )
        return list(MacOsSeatbeltSandbox().prepare(command, profile).argv)

    # Non-workspace legacy invocation: still deny all framework restricted_paths
    if not denied:
        return command
    rules = ["(version 1)", "(allow default)"]
    for restriction in denied:
        literal = json.dumps(str(restriction.path), ensure_ascii=True)
        operations = "file-read* file-write*" if restriction.deny_read else "file-write*"
        rules.append(f"(deny {operations} (subpath {literal}))")
        for ancestor in restriction.path.parents:
            if ancestor == Path("/"):
                break
            rules.append(f"(deny file-write-unlink (literal {json.dumps(str(ancestor))}))")
    return [str(sandbox), "-p", "\n".join(dict.fromkeys(rules)), *command]


def confine_workspace_command(
    command: Sequence[str],
    workspace: Path | str,
    *,
    allow_network: bool = False,
    backend: str | None = None,
) -> list[str]:
    """Explicit workspace sandbox helper supporting swappable SandboxPort backends."""
    from jaeger_authority import (
        ContainerSandbox,
        LinuxBwrapSandbox,
        MacOsSeatbeltSandbox,
        UnconfinedSandbox,
        default_os_sandbox,
    )
    from jaeger_contracts import SandboxProfile

    denied_reads = tuple(r.path for r in restricted_paths() if r.deny_read)
    profile = SandboxProfile(
        workspace=Path(workspace),
        denied_read_paths=denied_reads,
        allow_network=allow_network,
    )
    selected = (backend or os.environ.get("JAEGER_SANDBOX_BACKEND") or "").strip().lower()
    if selected == "seatbelt":
        sb = MacOsSeatbeltSandbox()
    elif selected == "bwrap":
        sb = LinuxBwrapSandbox()
    elif selected == "docker":
        sb = ContainerSandbox(cli="docker")
    elif selected == "unconfined":
        sb = UnconfinedSandbox()
    else:
        sb = default_os_sandbox()
    return list(sb.prepare(command, profile).argv)
