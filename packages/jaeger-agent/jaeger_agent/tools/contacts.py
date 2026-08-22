"""Contacts — one tool, ``lookup_contact``, over Contacts.app via
AppleScript. READ_ONLY.

The resolver ``send_email`` / ``send_message`` should reach for when the
user names a PERSON rather than an address: "email Sam the deck" needs
Sam's actual email first — this is that lookup. Both tools' docstrings
point back here (see ``tools/email.py`` and ``tools/messaging.py``).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_S = 10
_FIELD_SEP = "␟"
_VALUE_SEP = "␝"
_RECORD_SEP = "␞"


def _escape_applescript(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def lookup_contact(name: str) -> dict[str, Any]:
    """Look up a person in Contacts.app by (partial) name — returns
    every matching person's emails and phone numbers."""
    name_clean = (name or "").strip()
    if not name_clean:
        return {"found": False, "error": "empty name"}
    if platform.system() != "Darwin":
        return {"found": False,
                 "error": f"Contacts.app is only available on macOS (got {platform.system()})"}
    if shutil.which("osascript") is None:
        return {"found": False, "error": "osascript not on PATH (macOS-only utility)"}

    escaped = _escape_applescript(name_clean)
    script = (
        'tell application "Contacts"\n'
        f'set thePeople to (every person whose name contains "{escaped}")\n'
        "set output to \"\"\n"
        "repeat with p in thePeople\n"
        "  set emailList to \"\"\n"
        "  repeat with em in emails of p\n"
        f'    set emailList to emailList & (value of em as string) & "{_VALUE_SEP}"\n'
        "  end repeat\n"
        "  set phoneList to \"\"\n"
        "  repeat with ph in phones of p\n"
        f'    set phoneList to phoneList & (value of ph as string) & "{_VALUE_SEP}"\n'
        "  end repeat\n"
        f'  set output to output & (name of p as string) & "{_FIELD_SEP}" & '
        f'emailList & "{_FIELD_SEP}" & phoneList & "{_RECORD_SEP}"\n'
        "end repeat\n"
        "return output\n"
        "end tell"
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script], check=False, capture_output=True,
            text=True, timeout=_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"found": False, "error": f"Contacts lookup timed out after {_TIMEOUT_S}s"}
    except Exception as exc:  # noqa: BLE001
        return {"found": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"found": False,
                 "error": (out.stderr or out.stdout or "osascript failed").strip()}

    matches: list[dict[str, Any]] = []
    raw = out.stdout.strip()
    if raw:
        for record in raw.split(_RECORD_SEP):
            if not record.strip():
                continue
            fields = record.split(_FIELD_SEP)
            if len(fields) < 3:
                continue
            person_name, email_blob, phone_blob = fields[0], fields[1], fields[2]
            emails = [e for e in email_blob.split(_VALUE_SEP) if e]
            phones = [p for p in phone_blob.split(_VALUE_SEP) if p]
            matches.append({"name": person_name, "emails": emails, "phones": phones})

    if not matches:
        return {"found": False, "name": name_clean,
                 "error": f"no contact matching {name_clean!r} in Contacts.app"}
    return {"found": True, "name": name_clean, "count": len(matches), "matches": matches}


# ── Agent-facing tool wrapper ────────────────────────────────────────


@register_tool_from_function(name="lookup_contact", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="contacts", operation="lookup_contact",
               summary="look up a person in Contacts.app")
def _t_lookup_contact(name: str) -> dict:
    """Resolve a person's email(s)/phone(s) from Contacts.app by
    (partial) name — use this BEFORE send_email/send_message/
    create_event whenever the user names a PERSON rather than giving
    you a raw address ("email Sam the deck" -> lookup_contact(name="Sam")
    first, then send_email with the address it returns). Returns
    {found, matches: [{name, emails, phones}]} or {found: False,
    error} when nobody matches — never invent an address."""
    return lookup_contact(name=name)


__all__ = ["lookup_contact"]
