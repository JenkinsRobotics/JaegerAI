"""Sensitive-path guard for file reads (audit A5).

File *writes* are already hard-confined under ``<instance>/skills/`` by
``_resolve_under``. File *reads*, though, are deliberately unconfined
(``_resolve_read`` — so the agent can study its own source and the
repo). That carve-out means a tier-0, never-prompted ``read_file`` could
slurp ``~/.ssh/id_rsa`` or a ``.env`` full of API keys.

This module is the blocklist that closes that hole: a resolved path that
lands inside a known credential directory, or whose name is a known
secret file, is refused. It is a *resolved-path* check — no command
parsing, so no false positives from a command that merely mentions a
name. Ported (the idea) from hermes-agent's ``agent/file_safety.py``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

# Directories that exist only to hold credentials — any file inside is
# off-limits to a direct read.
_BLOCKED_DIRS = frozenset({".ssh", ".gnupg", ".aws", ".kube", ".docker"})

# Exact file names that typically hold secrets, wherever they live.
_BLOCKED_NAMES = frozenset({
    ".netrc", ".npmrc", ".pypirc", ".git-credentials",
    ".bash_history", ".zsh_history",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
})

# A `.env` whose suffix marks it a committed template, not a real secret
# store — these stay readable (`cp .env.example .env` is a real workflow).
_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")

_PROTECTED_WRITE_ROOTS = (
    Path("/System"), Path("/Library"), Path("/bin"), Path("/sbin"),
    Path("/usr"), Path("/etc"), Path("/private/etc"),
    Path("/private/var"), Path("/dev"), Path("/proc"), Path("/sys"),
    Path("/boot"),
)
_ALLOWED_TEMP_WRITE_ROOTS = (
    Path("/private/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir()).resolve(),
)


def is_sensitive_path(path: str | Path) -> str | None:
    """Return a human reason if ``path`` is a known secret location.

    ``path`` should already be resolved/absolute. Returns ``None`` for an
    ordinary file."""
    p = Path(path)
    parts = set(p.parts)
    name = p.name

    for d in _BLOCKED_DIRS:
        if d in parts:
            return f"{d}/ holds credentials and is off-limits to a direct read"
    if "Keychains" in p.parts:
        return "the macOS keychain is off-limits to a direct read"
    if name in _BLOCKED_NAMES:
        return f"{name} typically holds secrets and is off-limits"
    lname = name.lower()
    if lname == ".env" or (
        lname.startswith(".env.")
        and not lname.endswith(_ENV_TEMPLATE_SUFFIXES)
    ):
        return f"{name} is an environment file and may hold secrets"
    return None


def is_protected_write_path(path: str | Path) -> str | None:
    """Return a reason when owner approval must not authorize ``path``."""
    p = Path(path).resolve()
    sensitive = is_sensitive_path(p)
    if sensitive:
        return sensitive
    if any(p == root or root in p.parents for root in _ALLOWED_TEMP_WRITE_ROOTS):
        return None
    for root in _PROTECTED_WRITE_ROOTS:
        resolved = root.resolve()
        if p == resolved or resolved in p.parents:
            return f"{resolved}/ is an operating-system path and cannot be agent-written"
    return None


__all__ = ["is_protected_write_path", "is_sensitive_path"]
