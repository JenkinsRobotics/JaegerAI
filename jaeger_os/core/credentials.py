"""Credential storage and access.

The v2 agent contract is explicit: secrets live in `<instance>/credentials/`
and the *only* sanctioned read path is `get_credential(name)`. The agent
must never open files in `credentials/` directly — `tools.file_read`
already refuses, and this module is the matching positive path.

Layout:
    <instance>/credentials/
        <name>            # one file per secret, 0600 perms, single line of text

Perm enforcement is deliberate: if the file mode is looser than 0600, we
refuse to return the value. That prevents a misconfigured deploy from
quietly leaking a token to any local user.

Writes go through `set_credential(layout, name, value)` (called from the
CLI `--set-credential NAME` subcommand) so the wizard isn't the only
sanctioned writer. M3 will add an optional macOS Keychain backend behind
a config flag.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

from jaeger_os.core.instance.instance import InstanceLayout


_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
REQUIRED_MODE = 0o600


class CredentialError(RuntimeError):
    pass


def _validate_name(name: str) -> str:
    """Reject names that could escape the credentials/ dir (no slashes,
    dots, etc.). The agent contract is that credentials are looked up by
    a short identifier, not a path."""
    clean = (name or "").strip()
    if not clean:
        raise CredentialError("credential name must be non-empty")
    if not _NAME_RE.match(clean):
        raise CredentialError(
            f"invalid credential name {clean!r}; "
            "use letters/digits/underscore/dash/dot, must start with a letter, "
            "max 64 chars (no slashes)"
        )
    return clean


def _credential_path(layout: InstanceLayout, name: str) -> Path:
    name = _validate_name(name)
    return layout.credentials_dir / name


def _check_mode(path: Path) -> None:
    st = path.stat()
    # Mask to the permission bits; refuse if any group/other bits set, or
    # if owner has more than read+write (e.g. exec bit).
    mode = stat.S_IMODE(st.st_mode)
    if mode & 0o077:
        raise CredentialError(
            f"refusing to read {path.name!r}: file mode {oct(mode)} is too open. "
            f"Run `chmod 600 {path}` and try again."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_credential(layout: InstanceLayout, name: str) -> str:
    """Return the secret stored under <instance>/credentials/<name>.

    Raises CredentialError if the file is missing, unreadable, or has
    permissions looser than 0600. The trailing newline is stripped so
    callers get the bare token string."""
    target = _credential_path(layout, name)
    if not target.exists() or not target.is_file():
        raise CredentialError(f"no credential named {name!r} in {layout.credentials_dir}")
    _check_mode(target)
    return target.read_text(encoding="utf-8").rstrip("\n")


def set_credential(layout: InstanceLayout, name: str, value: str) -> Path:
    """Atomically write a credential with 0600 perms. Refuses empty values.

    Atomic write via temp + rename + fchmod so a partial write never
    leaves the file in a readable-to-group state. Returns the file path
    for the caller to confirm."""
    if value is None or not str(value):
        raise CredentialError("credential value must be non-empty")
    target = _credential_path(layout, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass

    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{name}.", suffix=".tmp")
    try:
        os.fchmod(fd, REQUIRED_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value if value.endswith("\n") else value + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except Exception:
        with _suppress():
            os.unlink(tmp_name)
        raise
    # Defensive: confirm perms post-rename (some filesystems lose mode on rename).
    os.chmod(target, REQUIRED_MODE)
    return target


def list_credentials(layout: InstanceLayout) -> list[str]:
    """Return the names of every credential currently stored. Values are
    NOT returned — only the names, so the human can audit what exists
    without leaking secrets."""
    if not layout.credentials_dir.exists():
        return []
    return sorted(
        p.name for p in layout.credentials_dir.iterdir()
        if p.is_file() and not p.name.startswith(".")
    )


def delete_credential(layout: InstanceLayout, name: str) -> bool:
    """Remove a credential by name. Returns whether it existed."""
    target = _credential_path(layout, name)
    if not target.exists():
        return False
    target.unlink()
    return True


# ---------------------------------------------------------------------------
# Tool-shape wrapper for the agent
# ---------------------------------------------------------------------------
def get_credential_tool_result(layout: InstanceLayout, name: str) -> dict[str, Any]:
    """Same as get_credential() but returns the dict shape every Jaeger
    tool uses (no exception leaks into the agent's response stream)."""
    try:
        value = get_credential(layout, name)
    except CredentialError as exc:
        return {"found": False, "error": str(exc)}
    return {"found": True, "name": _validate_name(name), "value": value}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _suppress:
    def __enter__(self): return self
    def __exit__(self, *exc): return True
