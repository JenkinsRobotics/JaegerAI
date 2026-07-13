"""Email — one tool, ``send_email``, modeled on ``tools/messaging.py``'s
``send_message``.

Backend ladder (Mac-centric, matching the native-first app-control
policy 0.9.3 Task 4 addendum sets for the rest of the toolbox):

  1. Mail.app via AppleScript (``agent/skills/macos_computer_v1/engines/
     applescript_engine.py`` is the sibling pattern for this — one
     ``osascript`` round-trip, no pointer movement). Primary backend:
     composes + sends through whatever account is already configured
     in Mail. If Mail has no account configured, that's an actionable
     error (tell the user to add one, or install himalaya) rather than
     a bare failure.
  2. himalaya (https://github.com/soywod/himalaya) CLI, if installed —
     detected via ``shutil.which``. Feeds it a standard RFC 822
     message over stdin (``himalaya message send``).

Tier-2 (EXTERNAL_EFFECT) like ``send_message`` — actually sending mail
is an external side effect, so it goes through the same
``requires_tier`` confirmation flow (headless-surface-aware since
0.9.3 Task 1) as everything else at this tier.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from email.message import EmailMessage
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier


def _escape_applescript(text: str) -> str:
    """Escape backslashes and double-quotes so ``text`` renders safely
    inside an AppleScript string literal."""
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def _mail_app_accounts() -> list[str]:
    """Names of every account configured in Mail.app — empty means
    Mail isn't set up (no inbox to send from)."""
    try:
        out = subprocess.run(
            ["osascript", "-e", 'tell application "Mail" to get name of every account'],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except Exception:  # noqa: BLE001 — treat any failure as "no accounts"
        return []
    if out.returncode != 0:
        return []
    return [a.strip() for a in out.stdout.strip().split(",") if a.strip()]


def _send_via_mail_app(to: str, subject: str, body: str, cc: str | None) -> dict[str, Any]:
    """Compose + send through Mail.app in a single ``osascript`` call."""
    if platform.system() != "Darwin":
        return {"sent": False, "error": "Mail.app is only available on macOS"}
    if shutil.which("osascript") is None:
        return {"sent": False, "error": "osascript not on PATH (macOS-only utility)"}

    accounts = _mail_app_accounts()
    if not accounts:
        return {
            "sent": False,
            "error": ("Mail.app has no email account configured — add one in "
                      "Mail > Settings > Accounts, or install the himalaya CLI "
                      "as an alternate backend (`brew install himalaya` / see "
                      "https://github.com/soywod/himalaya)."),
        }

    cc_clean = (cc or "").strip()
    cc_line = ""
    if cc_clean:
        cc_line = (
            "make new cc recipient at end of cc recipients "
            f'with properties {{address:"{_escape_applescript(cc_clean)}"}}\n'
        )
    script = (
        'tell application "Mail"\n'
        "set newMessage to make new outgoing message with properties "
        f'{{subject:"{_escape_applescript(subject)}", '
        f'content:"{_escape_applescript(body)}", visible:false}}\n'
        "tell newMessage\n"
        "make new to recipient at end of to recipients "
        f'with properties {{address:"{_escape_applescript(to)}"}}\n'
        f"{cc_line}"
        "end tell\n"
        "send newMessage\n"
        "end tell"
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            check=False, capture_output=True, text=True, timeout=15,
        )
    except Exception as exc:  # noqa: BLE001 — surface as a tool error, never raise
        return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"sent": False,
                 "error": (out.stderr or out.stdout or "osascript failed").strip()}
    return {"sent": True, "backend": "mail_app", "to": to, "subject": subject}


def _send_via_himalaya(to: str, subject: str, body: str, cc: str | None) -> dict[str, Any]:
    """Fall back to the himalaya CLI — feeds it a standard RFC 822
    message over stdin. Returns an actionable error if himalaya isn't
    installed instead of a bare failure."""
    himalaya_path = shutil.which("himalaya")
    if himalaya_path is None:
        return {"sent": False,
                 "error": ("himalaya CLI not found on PATH — install it "
                          "(`brew install himalaya` / cargo / see "
                          "https://github.com/soywod/himalaya) and configure "
                          "an account with `himalaya account configure`.")}

    msg = EmailMessage()
    msg["To"] = to
    cc_clean = (cc or "").strip()
    if cc_clean:
        msg["Cc"] = cc_clean
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        out = subprocess.run(
            [himalaya_path, "message", "send"],
            input=msg.as_string(), check=False, capture_output=True,
            text=True, timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 — surface as a tool error, never raise
        return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"sent": False,
                 "error": (out.stderr or out.stdout or "himalaya failed").strip()}
    return {"sent": True, "backend": "himalaya", "to": to, "subject": subject}


@register_tool_from_function
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="email",
               operation="send_email",
               summary="send an email")
def send_email(to: str, subject: str, body: str, cc: str | None = None) -> dict[str, Any]:
    """Send an email to `to` (a single address; for multiple, separate
    them with commas the way an email client would) with `subject` and
    `body`. `cc` is optional. If the user named a PERSON rather than
    giving you a raw address ("email Sam the deck"), resolve `to` via
    lookup_contact(name=...) first — never guess an address.

    Backend ladder: Mail.app via AppleScript is tried first (whatever
    account is already configured there); if Mail.app isn't available
    or has no account set up, the himalaya CLI is tried next if it's
    installed. If neither backend works, the error explains what's
    missing on both so the user knows how to fix it (add a Mail
    account, or install/configure himalaya) — never invent that the
    email sent when it didn't.

    EXTERNAL EFFECT: this actually sends the email — like send_message,
    it goes through the standard tier-2 confirmation flow before it
    runs. Returns {sent, backend, to, subject} or {sent: False, error}.
    """
    to_clean = (to or "").strip()
    subject_clean = (subject or "").strip()
    body_clean = body or ""
    if not to_clean or not subject_clean:
        return {"sent": False, "error": "to and subject are both required"}

    mail_result = _send_via_mail_app(to_clean, subject_clean, body_clean, cc)
    if mail_result.get("sent"):
        return mail_result
    mail_error = mail_result.get("error", "unknown Mail.app error")

    himalaya_result = _send_via_himalaya(to_clean, subject_clean, body_clean, cc)
    if himalaya_result.get("sent"):
        return himalaya_result
    himalaya_error = himalaya_result.get("error", "unknown himalaya error")

    return {
        "sent": False,
        "error": (f"no email backend available — Mail.app: {mail_error}; "
                  f"himalaya: {himalaya_error}"),
    }


__all__ = ["send_email"]
