"""Per-session trust — is a turn's session the OWNER (admin) or a stranger?

The trust model (operator-locked): there is ONE admin, the owner.

  • Local surfaces (CLI / GUI / TUI / voice) are the owner → admin by default
    (physical access is the confirmation).
  • Remote messaging sessions ("telegram:123") are NON-admin until the owner
    certifies that account from an admin context (the bridges mark them). An
    UNMARKED remote session is non-admin too — fail safe, never fail open.

The permission layer (BusConfirmationProvider) denies tier-gated actions for
non-admin sessions instead of prompting, so a stranger who reaches the bot gets
conversation + un-gated agentic work only — never higher-tier / system actions,
and no approval can elevate them.
"""

from __future__ import annotations

import threading

# Remote channel prefixes — sessions like "telegram:123". Anything else
# (a gui uuid, "voice", "") is a local surface = the owner.
_REMOTE_CHANNELS = ("telegram:", "discord:", "imessage:")

_admin: dict[str, bool] = {}
_lock = threading.Lock()


def _looks_remote(session: str) -> bool:
    return any(session.startswith(p) for p in _REMOTE_CHANNELS)


def mark_session(session: str, is_admin: bool) -> None:
    """A bridge declares whether this remote session is the certified owner.
    Called before the turn runs, so the permission check sees the right value."""
    if not session:
        return
    with _lock:
        _admin[session] = bool(is_admin)


def is_admin_session(session: str) -> bool:
    """True = the owner (full capabilities). Explicit marks win. Unmarked:
    local surfaces are the owner (True); remote channels fail safe (False)."""
    with _lock:
        if session in _admin:
            return _admin[session]
    return not _looks_remote(session)


def forget_session(session: str) -> None:
    with _lock:
        _admin.pop(session, None)
