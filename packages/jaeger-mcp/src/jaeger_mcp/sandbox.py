"""macOS Seatbelt stdio confinement for untrusted local MCP servers (codex/goose pattern).

Prevents third-party stdio MCP servers (e.g. npx packages) from reading private
credential directories (~/.ssh, ~/.aws, ~/.gnupg, ~/.jaeger/secrets.env) while
allowing normal tool execution inside approved paths.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


def _escape_sbpl(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"')


def build_mcp_seatbelt_profile(
    *,
    home_dir: str | Path | None = None,
    extra_deny_paths: list[str] | None = None,
    allow_network: bool = True,
) -> str:
    """Build a pragmatic macOS SBPL profile denying private credential paths."""
    home = str(Path(home_dir or Path.home()).expanduser().resolve())
    denied = [
        f"{home}/.ssh",
        f"{home}/.aws",
        f"{home}/.gnupg",
        f"{home}/.jaeger/secrets.env",
        f"{home}/.jaeger/secrets",
        f"{home}/.jaeger/caller_tokens",
        *(str(Path(p).expanduser()) for p in (extra_deny_paths or [])),
    ]
    lines = [
        "(version 1)",
        "(allow default)",
    ]
    if not allow_network:
        lines.append("(deny network*)")
    for p in denied:
        esc = _escape_sbpl(p)
        lines.append(f'(deny file-read* file-write* (subpath "{esc}"))')
        lines.append(f'(deny file-read* file-write* (literal "{esc}"))')
    return "\n".join(lines) + "\n"


def wrap_stdio_with_seatbelt(
    command: str,
    args: list[str],
    *,
    allow_network: bool = True,
    extra_deny_paths: list[str] | None = None,
) -> tuple[str, list[str], bool]:
    """Wrap (command, args) in ``sandbox-exec -p <profile>`` on macOS when available.

    Returns ``(effective_command, effective_args, sandboxed)``.
    """
    if platform.system() != "Darwin":
        return command, list(args), False
    sandbox_exec = shutil.which("sandbox-exec") or ("/usr/bin/sandbox-exec" if os.path.exists("/usr/bin/sandbox-exec") else None)
    if not sandbox_exec:
        return command, list(args), False
    profile = build_mcp_seatbelt_profile(
        allow_network=allow_network,
        extra_deny_paths=extra_deny_paths,
    )
    return sandbox_exec, ["-p", profile, command, *args], True
