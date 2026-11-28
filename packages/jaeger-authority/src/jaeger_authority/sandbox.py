"""Swappable SandboxPort backends: macOS Seatbelt, Linux bwrap, Container, Unconfined.

Combines:
- openai-codex: read-only-default Seatbelt/bwrap workspace profiles locking `.git`
- JaegerAI: ancestor `file-write-unlink` denials preventing parent-rename symlink bypasses
- hermes-agent: uniform swappable backend interface across local OS & container runtimes
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Sequence

from jaeger_contracts import SandboxProfile, SandboxSpec

_SEATBELT_BIN = Path("/usr/bin/sandbox-exec")
_SEATBELT_BASE = (Path(__file__).resolve().parent / "seatbelt_base.sbpl").read_text(encoding="utf-8")

_DEFAULT_SECRET_DIRS = (".ssh", ".aws", ".gnupg", ".kube", ".jaeger")


def _all_path_forms(path: Path) -> tuple[Path, ...]:
    """Return both lexical absolute and resolved realpath to defeat symlinks."""
    abs_p = path.expanduser().absolute()
    res_p = path.expanduser().resolve(strict=False)
    return (abs_p,) if abs_p == res_p else (abs_p, res_p)


def _default_denied_reads(profile: SandboxProfile) -> tuple[Path, ...]:
    home = Path.home()
    out: list[Path] = []
    for d in _DEFAULT_SECRET_DIRS:
        out.extend(_all_path_forms(home / d))
    for p in profile.denied_read_paths:
        out.extend(_all_path_forms(p))
    return tuple(dict.fromkeys(out))


def _default_ro_subpaths(profile: SandboxProfile) -> tuple[Path, ...]:
    out: list[Path] = []
    for base in (profile.workspace / ".git", profile.workspace / ".jaeger", *profile.read_only_subpaths):
        out.extend(_all_path_forms(base))
    return tuple(dict.fromkeys(out))


class MacOsSeatbeltSandbox:
    """Read-only-by-default macOS Seatbelt workspace sandbox."""

    @property
    def name(self) -> str:
        return "macos_seatbelt"

    def prepare(self, command: Sequence[str], profile: SandboxProfile) -> SandboxSpec:
        if not command:
            raise ValueError("Sandbox command cannot be empty.")

        writable: list[Path] = []
        for root in (profile.workspace, *profile.writable_roots):
            writable.extend(_all_path_forms(root))
        if profile.allow_tmp_writes:
            writable.extend([Path("/tmp"), Path("/private/tmp")])
        writable = list(dict.fromkeys(writable))

        denied_reads = _default_denied_reads(profile)
        ro_subpaths = _default_ro_subpaths(profile)
        denied_writes: list[Path] = list(ro_subpaths)
        for p in profile.denied_write_paths:
            denied_writes.extend(_all_path_forms(p))
        denied_writes = list(dict.fromkeys(denied_writes))

        lines = [
            _SEATBELT_BASE.rstrip(),
            "",
            "; Read filesystem by default EXCEPT explicit secret/authority stores",
            "(allow file-read*)",
        ]
        for p in denied_reads:
            lit = json.dumps(str(p), ensure_ascii=True)
            lines.append(f"(deny file-read* file-write* (subpath {lit}))")
            # JaegerAI invariant: block moving an ancestor away to swap a symlink
            for anc in p.parents:
                if anc == Path("/"):
                    break
                lines.append(f"(deny file-write-unlink (literal {json.dumps(str(anc), ensure_ascii=True)}))")

        # Preserve read-only execution of Jaeger's canonical venv (`~/.jaeger/venv`)
        # while keeping ~/.jaeger/secrets.env, instances, grants, and SQLite stores denied!
        for venv_path in _all_path_forms(Path.home() / ".jaeger" / "venv"):
            lines.append(f"(allow file-read* (subpath {json.dumps(str(venv_path), ensure_ascii=True)}))")

        lines.extend([
            "",
            "; Read-only by default: allow writes ONLY inside explicit workspace roots",
            "(deny file-write*)",
        ])
        for p in writable:
            lines.append(f"(allow file-write* (subpath {json.dumps(str(p), ensure_ascii=True)}))")

        lines.append("; Re-lock .git / .jaeger / explicit read-only subpaths inside workspace")
        for p in denied_writes:
            lines.append(f"(deny file-write* (subpath {json.dumps(str(p), ensure_ascii=True)}))")

        if profile.allow_network:
            lines.append("(allow network*)")
        else:
            lines.extend([
                "(deny network*)",
                "; Permit loopback-only sockets & local IPC for local tests (e.g. aiohttp TestServer)",
                '(allow network-bind (local ip "localhost:*"))',
                '(allow network-inbound (local ip "localhost:*"))',
                '(allow network-outbound (local ip "localhost:*"))',
                "(allow network* (local unix))",
            ])

        sbpl = "\n".join(dict.fromkeys(lines))
        argv = (str(_SEATBELT_BIN), "-p", sbpl, *command)
        return SandboxSpec(
            backend=self.name,
            argv=argv,
            read_only_default=True,
            protects_workspace_boundary=True,
            protects_git_metadata=True,
            protects_secret_stores=True,
            profile_text=sbpl,
        )


def _safe_exists(path: Path) -> bool:
    """Check existence without crashing when a parent sandbox denies stat()."""
    try:
        return path.exists()
    except OSError:
        return False


class LinuxBwrapSandbox:
    """Read-only-by-default Linux Bubblewrap workspace sandbox."""

    @property
    def name(self) -> str:
        return "linux_bwrap"

    def prepare(self, command: Sequence[str], profile: SandboxProfile) -> SandboxSpec:
        if not command:
            raise ValueError("Sandbox command cannot be empty.")
        bwrap = shutil.which("bwrap") or "/usr/bin/bwrap"
        ws = profile.workspace.expanduser().resolve(strict=False)

        argv: list[str] = [
            bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-ipc",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
        ]
        if not profile.allow_network:
            argv.append("--unshare-net")
        if profile.allow_tmp_writes:
            argv.extend(["--tmpfs", "/tmp"])

        for root in dict.fromkeys([ws, *(p.expanduser().resolve(strict=False) for p in profile.writable_roots)]):
            argv.extend(["--bind", str(root), str(root)])

        for ro in _default_ro_subpaths(profile):
            if _safe_exists(ro):
                argv.extend(["--ro-bind", str(ro), str(ro)])

        for denied in _default_denied_reads(profile):
            if _safe_exists(denied):
                argv.extend(["--tmpfs", str(denied)])

        argv.extend(["--chdir", str(ws), "--", *command])
        return SandboxSpec(
            backend=self.name,
            argv=tuple(argv),
            read_only_default=True,
            protects_workspace_boundary=True,
            protects_git_metadata=True,
            protects_secret_stores=True,
            profile_text=" ".join(argv),
        )


class ContainerSandbox:
    """Swappable container execution wrapper (Docker or Apple `container` CLI)."""

    def __init__(self, *, cli: str = "docker", image: str = "python:3.12-slim") -> None:
        self._cli = cli
        self._image = image

    @property
    def name(self) -> str:
        return f"container_{Path(self._cli).name}"

    def prepare(self, command: Sequence[str], profile: SandboxProfile) -> SandboxSpec:
        if not command:
            raise ValueError("Sandbox command cannot be empty.")
        ws = profile.workspace.expanduser().resolve(strict=False)
        argv = [
            self._cli, "run", "--rm",
            "--read-only",
            "--network", "bridge" if profile.allow_network else "none",
            "-v", f"{ws}:{ws}:rw",
            "-w", str(ws),
        ]
        if (ws / ".git").exists():
            argv.extend(["-v", f"{ws / '.git'}:{ws / '.git'}:ro"])
        if profile.allow_tmp_writes:
            argv.extend(["--tmpfs", "/tmp:rw,noexec,nosuid"])
        argv.append(self._image)
        argv.extend(command)
        return SandboxSpec(
            backend=self.name,
            argv=tuple(argv),
            read_only_default=True,
            protects_workspace_boundary=True,
            protects_git_metadata=True,
            protects_secret_stores=True,
            profile_text=" ".join(argv),
        )


class UnconfinedSandbox:
    """Explicit opt-in unconfined runner (used ONLY for FULL_ACCESS or diagnostics)."""

    @property
    def name(self) -> str:
        return "unconfined"

    def prepare(self, command: Sequence[str], profile: SandboxProfile) -> SandboxSpec:
        if not command:
            raise ValueError("Sandbox command cannot be empty.")
        return SandboxSpec(
            backend=self.name,
            argv=tuple(command),
            read_only_default=False,
            protects_workspace_boundary=False,
            protects_git_metadata=False,
            protects_secret_stores=False,
            profile_text="",
        )


def default_os_sandbox() -> MacOsSeatbeltSandbox | LinuxBwrapSandbox:
    """Select the native OS sandbox for the current host (fail-closed if unsupported)."""
    if sys.platform == "darwin":
        if not _SEATBELT_BIN.is_file():
            raise PermissionError("macOS sandbox-exec not found; refusing unconfined execution.")
        return MacOsSeatbeltSandbox()
    if sys.platform == "linux":
        return LinuxBwrapSandbox()
    raise PermissionError(f"Unsupported OS {sys.platform!r} for native sandbox; refusing unconfined execution.")
