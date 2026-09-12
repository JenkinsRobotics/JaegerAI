"""Operator identity read from the host — never asked for.

The installer greets the operator by name. Asking "what should I call you?"
would be the first thing the system does, and it would be asking for
something the machine already knows — which reads as a form, not as
something that has been watching the environment it was installed into.

Sources, in order of trust: the OS account's full name, the account's short
name, then the home directory's basename. Anything that looks like a
service account or a placeholder is rejected rather than used, because
"Welcome, admin" is worse than no name at all.
"""

from __future__ import annotations

import os
import pwd
import re
from pathlib import Path

#: Account names that are technically valid and useless as a form of
#: address. Greeting someone as "root" or "user" is worse than not.
_REJECTED = {
    "root", "admin", "administrator", "user", "guest", "nobody",
    "system", "daemon", "operator", "localadmin", "test", "ubuntu",
}


def _clean(candidate: str | None) -> str | None:
    """A usable given name, or None."""
    if not candidate:
        return None
    text = candidate.strip()
    if not text or text.lower() in _REJECTED:
        return None
    # Full names arrive as "Matthew Jenkins"; address uses the first part.
    first = text.split()[0]
    # Reject anything that is not plausibly a name — digits, service
    # suffixes, single letters.
    if len(first) < 2 or not re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", first):
        return None
    if first.lower() in _REJECTED:
        return None
    return first[:1].upper() + first[1:]


def operator_name() -> str | None:
    """The operator's given name from the host, or None if unusable.

    Never raises: a machine with an unusual account setup gets an
    unaddressed greeting, which is a smaller failure than a crash on the
    very first thing the product does.
    """
    try:
        entry = pwd.getpwuid(os.getuid())
    except (KeyError, OSError):
        entry = None

    if entry is not None:
        # GECOS full name is the most human of the three.
        gecos = (entry.pw_gecos or "").split(",")[0]
        if (name := _clean(gecos)):
            return name
        if (name := _clean(entry.pw_name)):
            return name

    try:
        return _clean(Path.home().name)
    except (OSError, RuntimeError):
        return None


def greeting_address() -> str:
    """How the installer opens — with a name when it has one.

    Falls back to an unaddressed greeting rather than a placeholder. "Hello,
    user" is worse than "Hello."
    """
    name = operator_name()
    return f"Hello, {name}." if name else "Hello."


__all__ = ["greeting_address", "operator_name"]
