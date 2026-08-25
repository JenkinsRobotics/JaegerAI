"""Email — Mail.app tools, plus ``send_email``.

Reads (``list_mailboxes``, ``list_mail``) are bounded AppleScript
round-trips with a hard timeout. Never query ``every message`` of a
mailbox — that locks AppleEvents until Mail.app's 120s timeout and is
the 60-tool organizer loop. Writes (``move_mail``, ``batch_move``,
``sweep_mail``, ``send_email``) are tier-2.

Gmail nests Trash/Spam/All Mail under container mailbox ``[Gmail]``.
Mailbox arguments are resolved by walking ``mailboxes of acc`` and
expanding aliases (``trash`` / ``junk`` / ``archive``) so callers never
have to guess ``mailbox "Trash" of mailbox "[Gmail]"``.

Backend ladder for send (Mac-centric):

  1. Mail.app via AppleScript (one ``osascript`` round-trip).
  2. himalaya CLI, if installed.

Organize / triage on macOS MUST use ``list_mailboxes`` → ``list_mail``
/ ``plan_mail_triage`` → ``batch_move`` (see the ``macos-mail-organizer``
skill). Raw ``execute_code`` / ``osascript`` against Mail is the failure
mode those tools exist to replace.

Deep clean is keep-first and paginated: receipts/finance are never
auto-trashed, a body peek can only upgrade a keep, and after a move the
next page is offset 0 (the inbox compacted).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from email.message import EmailMessage
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_S = 15
_MAX_FETCH = 25
_FIELD_SEP = "|||"


def _escape_applescript(text: str) -> str:
    """Escape backslashes and double-quotes so ``text`` renders safely
    inside an AppleScript string literal."""
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def _coerce_int(
    value: Any,
    default: int,
    *,
    lo: int | None = None,
    hi: int | None = None,
) -> int:
    """Best-effort int for model-emitted args. Bools are not ints."""
    if isinstance(value, bool) or value is None:
        n = default
    else:
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


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


@register_tool_from_function(side_effect="external")
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


def _not_macos() -> dict[str, Any]:
    return {"ok": False, "success": False, "error": "Mail.app is only available on macOS"}


def _envelope(
    *,
    ok: bool,
    error: str | None = None,
    moved_count: int = 0,
    raw_output: str = "",
    timed_out: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """Structured observation every Mail.app tool returns.

    ``ok`` and ``success`` stay in lockstep so the 2-strike loop
    backstop (``semantic_failure_signature``) and the skill's evaluation
    gate inspect the same bit.
    """
    payload: dict[str, Any] = {
        "ok": ok,
        "success": ok,
        "error": error,
        "moved_count": moved_count,
        "timed_out": timed_out,
    }
    if raw_output:
        payload["raw_output"] = raw_output
    payload.update(extra)
    return payload


def run_applescript(script: str, timeout_seconds: int = _TIMEOUT_S) -> dict[str, Any]:
    """One bounded osascript call. Never raises into the agent loop.

    Returns ``{ok, success, error, raw_output, exit_code, timed_out}``.
    """
    if platform.system() != "Darwin":
        return {
            **_not_macos(), "exit_code": 1, "timed_out": False, "raw_output": "",
            "moved_count": 0,
        }
    if shutil.which("osascript") is None:
        return _envelope(
            ok=False, exit_code=1, timed_out=False, raw_output="",
            error="osascript not on PATH (macOS-only utility)",
        )
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            check=False, capture_output=True, text=True, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _envelope(
            ok=False, exit_code=124, timed_out=True, raw_output="",
            error=(
                f"AppleScript timed out after {timeout_seconds}s. Do not repeat "
                "without narrowing the query (smaller batch, named account)."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope(
            ok=False, exit_code=1, timed_out=False, raw_output="",
            error=f"{type(exc).__name__}: {exc}",
        )
    raw = (out.stdout or "").strip()
    if out.returncode != 0:
        payload = _envelope(
            ok=False, exit_code=out.returncode, timed_out=False,
            error=(out.stderr or out.stdout or "osascript failed").strip(),
        )
        payload["raw_output"] = raw
        return payload
    payload = _envelope(ok=True, exit_code=0, timed_out=False, error=None)
    payload["raw_output"] = raw
    return payload


def _run_osascript(script: str, timeout_s: int = _TIMEOUT_S) -> dict[str, Any]:
    """Compat alias — prefer :func:`run_applescript`."""
    return run_applescript(script, timeout_seconds=timeout_s)


# Universal mailbox aliases. ``"trash"``, ``"[Gmail]/Trash"``, and
# ``"Deleted Messages"`` all expand to the same candidate set so the
# AppleScript walker can match Gmail's nested container without the
# model guessing folder names.
_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "trash": ("Trash", "Deleted Messages", "Deleted Items", "Bin"),
    "deleted": ("Trash", "Deleted Messages", "Deleted Items", "Bin"),
    "junk": ("Spam", "Junk", "Junk Email", "Bulk"),
    "spam": ("Spam", "Junk", "Junk Email", "Bulk"),
    "archive": ("Archive", "All Mail"),
    # Keep folders: exact name first (two-pass walk), then Archive so a
    # missing Receipts/Finance/GitHub-Noise folder never dumps mail.
    "receipts": ("Receipts", "Archive", "All Mail"),
    "finance": ("Finance", "Archive", "All Mail"),
    "github-noise": ("GitHub-Noise", "Archive", "All Mail"),
}

# Keep-first classification. Receipts and finance ALWAYS beat a
# noreply@ sender — Amazon/Stripe receipts commonly arrive from
# no-reply addresses. Bare noreply without a promo/receipt signal
# stays Action (keep in inbox) so a deep clean never dumps reference
# mail. Only high-confidence marketing and GitHub notifications are
# auto-trash candidates.
_GITHUB_NOISE_SENDERS = (
    "notifications@github.com",
    "noreply@github.com",
)
# Security / auth GitHub mail is reference material, not inbox noise.
_GITHUB_KEEP_NEEDLES = (
    "security", "vulnerabilit", "dependabot", "authorization",
    "sign in", "signed in", "ssh key", "2fa", "two-factor",
    "two factor", "passkey", "recovery code",
)
_RECEIPT_NEEDLES = (
    "invoice", "receipt", "order confirmation", "your order", "order #",
    "tracking number", "shipping confirmation", "payment receipt",
    "boarding pass", "itinerary", "e-ticket",
)
_FINANCE_NEEDLES = (
    "statement", "wire transfer", "payment due", "account alert",
    "tax document", "1099", "w-2", "unusual activity",
)
_PROMO_SENDER_NEEDLES = (
    "newsletter@", "marketing@", "promo@", "deals@",
)
# Subject-only. Never match these against a body snippet — transactional
# mail (receipts, security notices) almost always contains "unsubscribe".
_PROMO_SUBJECT_NEEDLES = (
    "newsletter", "weekly deals", "daily deals", "% off", " percent off",
    "is now on sale", "promotional",
)
_NOREPLY_SENDER_NEEDLES = (
    "noreply@", "no-reply@", "do-not-reply@", "donotreply@",
    "mailer-daemon@", "notifications@", "notify@",
)
# Backward-compat name used by older tests / comments.
_MARKETING_SENDER_NEEDLES = _PROMO_SENDER_NEEDLES + _NOREPLY_SENDER_NEEDLES

_MAX_SNIPPET = 800
_MAX_SNIPPET_OUT = 240
_MAX_READ = 5
_MAX_PEEK_PER_PAGE = 5  # one osascript; _read_mail_impl clamps to _MAX_READ

_SWEEPER_PROMPT = (
    "You are running the scheduled inbox sweeper (macos-mail-organizer). "
    "Call sweep_mail(dry_run=false). File only high-confidence GitHub-Noise "
    "and promotional trash. Never trash receipts, finance, or uncertain "
    "noreply. Do not write AppleScript and do not call execute_code/"
    "osascript/terminal against Mail.app. If success is false, stop and "
    "report the error - do not retry. Reply with moved_count and a "
    "one-line summary of what was filed."
)

# Nested-mailbox walker. Gmail's Trash is `mailbox "Trash" of mailbox
# "[Gmail]"` — a direct `mailbox "Trash" of account` throws. Two-pass
# (exact path/name, then alias) so a real Archive folder wins over
# Gmail's All Mail alias.
_AS_RESOLVER = r'''
on _aliasHit(nameOrPath, aliasCSV)
    ignoring case
        if aliasCSV is "" then return false
        set oldDelims to AppleScript's text item delimiters
        set AppleScript's text item delimiters to ","
        set aliasItems to text items of aliasCSV
        set AppleScript's text item delimiters to oldDelims
        repeat with a in aliasItems
            if nameOrPath is (contents of a) then return true
        end repeat
        return false
    end ignoring
end _aliasHit

on _walk(mbs, prefix, wanted, aliasCSV, exactOnly, depth)
    if depth > 5 then return missing value
    tell application "Mail"
        repeat with mb in mbs
            set n to name of mb as string
            if prefix is "" then
                set p to n
            else
                set p to prefix & "/" & n
            end if
            ignoring case
                if p is wanted or n is wanted then return mb
            end ignoring
            if exactOnly is false then
                if my _aliasHit(n, aliasCSV) then return mb
                if my _aliasHit(p, aliasCSV) then return mb
            end if
            try
                set kids to mailboxes of mb
                if (count of kids) > 0 then
                    set nested to my _walk(kids, p, wanted, aliasCSV, exactOnly, depth + 1)
                    if nested is not missing value then return nested
                end if
            end try
        end repeat
    end tell
    return missing value
end _walk

on resolveMb(accName, wanted, aliasCSV)
    tell application "Mail"
        set acc to missing value
        repeat with candidate in accounts
            ignoring case
                if (name of candidate as string) is accName then
                    set acc to candidate
                    exit repeat
                end if
            end ignoring
        end repeat
        if acc is missing value then error "No Mail account named " & accName
        ignoring case
            if wanted is "INBOX" then
                try
                    return mailbox "INBOX" of acc
                end try
            end if
        end ignoring
        set found to my _walk(mailboxes of acc, "", wanted, aliasCSV, true, 0)
        if found is missing value then
            set found to my _walk(mailboxes of acc, "", wanted, aliasCSV, false, 0)
        end if
        if found is missing value then error "Can't get mailbox " & wanted & " of account " & accName & ". Call list_mailboxes and use an exact path."
        return found
    end tell
end resolveMb
'''


def alias_candidates(mailbox: str) -> list[str]:
    """Return Mail.app names that should match ``mailbox``.

    ``"trash"``, ``"[Gmail]/Trash"``, and ``"Deleted Messages"`` all
    expand to the same trash-folder set.
    """
    raw = (mailbox or "").strip()
    if not raw:
        return ["INBOX"]
    key = raw.replace("\\", "/").strip()
    leaf = key.split("/")[-1]
    lowered = {key.lower(), leaf.lower()}
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        cleaned = name.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)

    add(key)
    if leaf != key:
        add(leaf)
    for alias_key, names in _ALIAS_GROUPS.items():
        group_lower = {alias_key, *[n.lower() for n in names]}
        if lowered & group_lower:
            add(alias_key)
            for n in names:
                add(n)
    return out


def _resolve_call(var_name: str, account: str, mailbox: str) -> str:
    """AppleScript that sets ``var_name`` to the resolved mailbox object."""
    acc = _escape_applescript(account)
    wanted = _escape_applescript((mailbox or "INBOX").strip() or "INBOX")
    aliases = _escape_applescript(",".join(alias_candidates(mailbox)))
    return f'set {var_name} to my resolveMb("{acc}", "{wanted}", "{aliases}")'


def _normalize_ids(message_ids: Any) -> list[str]:
    """Accept a list, a single id, or a comma-separated string.

    Bools are excluded (``True`` is an ``int`` in Python). Duplicates
    are dropped, order preserved.
    """
    if message_ids is None or isinstance(message_ids, bool):
        return []
    if isinstance(message_ids, (int, float)):
        raw = [str(int(message_ids))]
    elif isinstance(message_ids, str):
        raw = [p.strip() for p in message_ids.split(",") if p.strip()]
    elif isinstance(message_ids, (list, tuple)):
        raw = []
        for item in message_ids:
            raw.extend(_normalize_ids(item))
    else:
        text = str(message_ids).strip()
        raw = [text] if text else []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _needle_hit(needles: tuple[str, ...], text: str) -> str | None:
    for needle in needles:
        if needle in text:
            return needle
    return None


def classify_filing(
    sender: str,
    subject: str = "",
    snippet: str = "",
) -> dict[str, Any]:
    """Conservative filing proposal for one message.

    Keep-first: receipts/finance win over noreply. Uncertain noreply
    stays ``Action`` (inbox) with ``verify=True``. Promo needles match
    subject/sender only — never a body snippet — so an unsubscribe
    footer cannot demote a receipt.
    """
    sender_l = (sender or "").lower()
    subject_l = (subject or "").lower()
    snippet_l = (snippet or "").lower()
    keep_blob = f"{sender_l} {subject_l} {snippet_l}"

    if any(n in sender_l for n in _GITHUB_NOISE_SENDERS):
        keep_hit = _needle_hit(_GITHUB_KEEP_NEEDLES, keep_blob)
        if keep_hit:
            return {
                "category": "Action",
                "confidence": "high",
                "keep": True,
                "destination": None,
                "verify": False,
                "reason": f"GitHub security/authentication notice ({keep_hit}) - leave in inbox",
            }
        return {
            "category": "GitHub-Noise",
            "confidence": "high",
            "keep": True,
            "destination": "GitHub-Noise",
            "verify": False,
            "reason": "GitHub notification - file to GitHub-Noise, do not trash",
        }
    receipt_hit = _needle_hit(_RECEIPT_NEEDLES, keep_blob)
    if receipt_hit:
        return {
            "category": "Receipts", "confidence": "high" if snippet else "medium",
            "keep": True, "destination": "Receipts", "verify": not bool(snippet),
            "reason": f"keep-for-reference ({receipt_hit})",
        }
    finance_hit = _needle_hit(_FINANCE_NEEDLES, keep_blob)
    if finance_hit:
        return {
            "category": "Finance", "confidence": "high" if snippet else "medium",
            "keep": True, "destination": "Finance", "verify": not bool(snippet),
            "reason": f"keep-for-reference ({finance_hit})",
        }
    promo_sender = _needle_hit(_PROMO_SENDER_NEEDLES, sender_l)
    promo_subject = _needle_hit(_PROMO_SUBJECT_NEEDLES, subject_l)
    noreply_sender = _needle_hit(_NOREPLY_SENDER_NEEDLES, sender_l)
    if promo_subject and (promo_sender or noreply_sender):
        return {
            "category": "Trash",
            "confidence": "high",
            "keep": False, "destination": "trash",
            "verify": False,
            "reason": f"promotional sender and subject ({promo_sender or noreply_sender}; {promo_subject})",
        }
    if promo_sender or promo_subject:
        return {
            "category": "Action",
            "confidence": "low",
            "keep": True, "destination": None,
            "verify": True,
            "reason": f"possible promotion ({promo_sender or promo_subject}) - verify before trash",
        }
    if noreply_sender:
        return {
            "category": "Action", "confidence": "low", "keep": True,
            "destination": None, "verify": True,
            "reason": "noreply without receipt/promo signal - peek before filing",
        }
    return {
        "category": "Action", "confidence": "medium", "keep": True,
        "destination": None, "verify": False,
        "reason": "personal or unlabeled - leave in inbox",
    }


def _prefer_keep(header: dict[str, Any], peeked: dict[str, Any]) -> dict[str, Any]:
    """A body peek may upgrade to keep; it must never demote to trash."""
    if header.get("keep") and not peeked.get("keep"):
        merged = dict(header)
        merged["reason"] = (
            f"{header.get('reason')}; peek did not override keep"
        )
        return merged
    return peeked


def classify_message(sender: str, subject: str = "", snippet: str = "") -> str:
    """Map a header to an executive category (keep-first)."""
    return str(classify_filing(sender, subject, snippet)["category"])


def pick_keep_mailbox(category: str, mailboxes: list[str] | None) -> str | None:
    """Resolve a keep-for-reference folder from list_mailboxes names.

    Missing ``Receipts`` / ``Finance`` fall back to Archive (keep), never
    Trash. ``Action`` stays in the inbox (``None``).
    """
    filing = {
        "Receipts": ("receipts",),
        "Finance": ("finance",),
        "GitHub-Noise": ("github-noise", "github noise"),
        "Archive": ("archive", "all mail"),
        "Trash": ("trash", "deleted messages", "deleted items", "bin"),
    }
    if category == "Action":
        return None
    wanted = filing.get(category) or filing["Archive"]
    by_lower = {m.lower(): m for m in (mailboxes or [])}
    for key in wanted:
        if key in by_lower:
            return by_lower[key]
    if category in ("Receipts", "Finance", "GitHub-Noise"):
        for key in filing["Archive"]:
            if key in by_lower:
                return by_lower[key]
        return "archive"
    if category == "Trash":
        return "trash"
    return None


@register_tool_from_function(side_effect="read")
def list_mailboxes() -> dict[str, Any]:
    """List Mail.app accounts and their mailboxes, including nested
    Gmail paths like `[Gmail]/Trash`. Call this BEFORE any inbox query
    — mailboxes nest under accounts (iCloud, Exchange, Google, Yahoo!).
    Never query mailbox "INBOX" at the root.
    """
    script = '''
    tell application "Mail"
        set out to ""
        repeat with acc in accounts
            set accName to name of acc as string
            set mbNames to "INBOX,"
            set mbNames to mbNames & my collectPaths(mailboxes of acc, "")
            set out to out & accName & "|||" & mbNames & linefeed
        end repeat
        return out
    end tell

    on collectPaths(mbs, prefix)
        set collected to ""
        tell application "Mail"
            repeat with mb in mbs
                set n to name of mb as string
                if prefix is "" then
                    set p to n
                else
                    set p to prefix & "/" & n
                end if
                ignoring case
                    if p is not "INBOX" and n is not "INBOX" then
                        set collected to collected & p & ","
                    end if
                end ignoring
                try
                    set kids to mailboxes of mb
                    if (count of kids) > 0 then
                        set collected to collected & my collectPaths(kids, p)
                    end if
                end try
            end repeat
        end tell
        return collected
    end collectPaths
    '''
    res = run_applescript(script, timeout_seconds=10)
    if not res.get("ok"):
        return _envelope(
            ok=False, listed=False, accounts=[], error=res.get("error"),
            timed_out=bool(res.get("timed_out")),
        )
    accounts: list[dict[str, Any]] = []
    for line in (res.get("raw_output") or "").splitlines():
        if "|||" not in line:
            continue
        name, mbs = line.split("|||", 1)
        mailboxes = [m.strip() for m in mbs.split(",") if m.strip()]
        # INBOX is often a special mailbox not listed under `mailboxes of acc`.
        if "INBOX" not in {m.upper() for m in mailboxes}:
            mailboxes = ["INBOX", *mailboxes]
        accounts.append({"name": name.strip(), "mailboxes": mailboxes})
    return _envelope(
        ok=True, listed=True, accounts=accounts, count=len(accounts), error=None,
    )


@register_tool_from_function(side_effect="read")
def list_mail(
    account: str,
    mailbox: str = "INBOX",
    limit: int = 10,
    unread_only: bool = False,
    offset: int = 0,
) -> dict[str, Any]:
    """Fetch headers for N messages in one mailbox, optionally paging.

    `account` is the Mail.app account name from list_mailboxes (e.g.
    "iCloud", "Google"). `mailbox` defaults to INBOX and is resolved
    through nested Gmail containers and aliases (`trash`, `junk`,
    `archive`). `limit` is hard-clamped to 25 — larger fetches freeze
    AppleEvents. `offset` is how many messages to skip (0 = newest).
    Prefer unread_only=true for a quick glance; deep-clean pages with
    unread_only=false and the returned next_offset. Returns
    {ok, success, messages, count, offset, next_offset}.
    """
    account = (account or "").strip()
    if not account:
        return _envelope(
            ok=False, messages=[], count=0, timed_out=False,
            error="account is required; call list_mailboxes first",
        )
    limit = _coerce_int(limit, 10, lo=1, hi=_MAX_FETCH)
    offset = _coerce_int(offset, 0, lo=0)
    # Fetch a slightly larger header window when unread_only so we can
    # filter in Python — `whose read status is false` over a huge INBOX
    # is the AppleEvents lock this tool exists to avoid.
    fetch = limit if not unread_only else min(_MAX_FETCH, max(limit * 3, limit))
    start_index = offset + 1
    end_index = offset + fetch
    resolve = _resolve_call("targetMb", account, mailbox)
    script = f'''
    {_AS_RESOLVER}
    tell application "Mail"
        try
            {resolve}
            set startIndex to {start_index}
            set endIndex to {end_index}
            set outLines to {{}}
            repeat with i from startIndex to endIndex
                try
                    set m to message i of targetMb
                    set mid to id of m as string
                    set s to subject of m
                    set sndr to sender of m
                    set dt to (date received of m) as string
                    set isRead to (read status of m) as string
                    set end of outLines to mid & "{_FIELD_SEP}" & s & "{_FIELD_SEP}" & sndr & "{_FIELD_SEP}" & dt & "{_FIELD_SEP}" & isRead
                end try
            end repeat
            set AppleScript's text item delimiters to linefeed
            return (outLines as string)
        on error errMsg
            return "ERROR:" & errMsg
        end try
    end tell
    '''
    res = run_applescript(script, timeout_seconds=_TIMEOUT_S)
    if not res.get("ok"):
        return _envelope(
            ok=False, messages=[], count=0,
            error=res.get("error"), timed_out=bool(res.get("timed_out")),
            account=account, mailbox=mailbox, offset=offset, next_offset=None,
        )
    raw = res.get("raw_output") or ""
    if raw.startswith("ERROR:"):
        return _envelope(
            ok=False, messages=[], count=0, error=raw[6:].strip(),
            account=account, mailbox=mailbox, offset=offset, next_offset=None,
        )
    if raw in ("COUNT:0", ""):
        return _envelope(
            ok=True, messages=[], count=0, error=None,
            account=account, mailbox=mailbox, offset=offset, next_offset=None,
        )
    messages: list[dict[str, Any]] = []
    for idx, line in enumerate(raw.splitlines(), start=1):
        parts = line.split(_FIELD_SEP, 4)
        if len(parts) < 5:
            continue
        is_read = parts[4].lower() == "true"
        if unread_only and is_read:
            continue
        messages.append({
            "id": parts[0],
            "index": offset + idx,
            "subject": parts[1],
            "sender": parts[2],
            "date": parts[3],
            "is_read": is_read,
        })
        if len(messages) >= limit:
            break
    if unread_only:
        next_offset = offset + fetch if len(raw.splitlines()) >= fetch else None
    else:
        next_offset = offset + len(messages) if len(messages) >= limit else None
    return _envelope(
        ok=True,
        messages=messages,
        count=len(messages),
        account=account,
        mailbox=mailbox,
        unread_only=unread_only,
        offset=offset,
        next_offset=next_offset,
        error=None,
    )


def _read_mail_impl(
    account: str,
    mailbox: str,
    message_ids: Any,
) -> dict[str, Any]:
    """Fetch a short plaintext snippet for 1..5 messages by id."""
    acc = (account or "").strip()
    src = (mailbox or "").strip() or "INBOX"
    ids = _normalize_ids(message_ids)[:_MAX_READ]
    if not acc:
        return _envelope(
            ok=False, messages=[], count=0,
            error="account is required; call list_mailboxes first",
        )
    if not ids:
        return _envelope(
            ok=False, messages=[], count=0,
            error="message_ids is required; pass numeric ids from list_mail",
        )
    bad = [i for i in ids if not i.isdigit()]
    if bad:
        return _envelope(
            ok=False, messages=[], count=0,
            error=f"message_ids must be numeric Mail.app ids, got {bad!r}",
        )
    id_list = ", ".join(ids)
    src_call = _resolve_call("src", acc, src)
    script = f'''
    {_AS_RESOLVER}
    on _flatten(s, maxLen)
        set t to s as string
        set oldDelims to AppleScript's text item delimiters
        set AppleScript's text item delimiters to {{return, linefeed}}
        set bits to text items of t
        set AppleScript's text item delimiters to " "
        set t to bits as string
        set AppleScript's text item delimiters to oldDelims
        if (length of t) > maxLen then set t to text 1 thru maxLen of t
        return t
    end _flatten
    tell application "Mail"
        try
            {src_call}
            set outLines to {{}}
            set idList to {{{id_list}}}
            repeat with mid in idList
                try
                    set thisId to contents of mid
                    set m to first message of src whose id is thisId
                    set s to my _flatten(subject of m, 200)
                    set sndr to my _flatten(sender of m, 200)
                    set dt to (date received of m) as string
                    set bodyText to ""
                    try
                        set bodyText to my _flatten(content of m, {_MAX_SNIPPET})
                    end try
                    set end of outLines to (thisId as string) & "{_FIELD_SEP}" & s & "{_FIELD_SEP}" & sndr & "{_FIELD_SEP}" & dt & "{_FIELD_SEP}" & bodyText
                end try
            end repeat
            set AppleScript's text item delimiters to linefeed
            return (outLines as string)
        on error errMsg
            return "ERROR:" & errMsg
        end try
    end tell
    '''
    res = run_applescript(script, timeout_seconds=_TIMEOUT_S)
    if not res.get("ok"):
        return _envelope(
            ok=False, messages=[], count=0,
            error=res.get("error"), timed_out=bool(res.get("timed_out")),
            account=acc, mailbox=src,
        )
    raw = res.get("raw_output") or ""
    if raw.startswith("ERROR:"):
        return _envelope(
            ok=False, messages=[], count=0, error=raw[6:].strip(),
            account=acc, mailbox=src,
        )
    messages: list[dict[str, Any]] = []
    for line in raw.splitlines():
        parts = line.split(_FIELD_SEP, 4)
        if len(parts) < 4:
            continue
        snippet = parts[4] if len(parts) > 4 else ""
        messages.append({
            "id": parts[0],
            "subject": parts[1],
            "sender": parts[2],
            "date": parts[3],
            "snippet": snippet.replace(_FIELD_SEP, " ")[:_MAX_SNIPPET],
        })
    return _envelope(
        ok=True, messages=messages, count=len(messages), error=None,
        account=acc, mailbox=src, message_ids=ids,
    )


@register_tool_from_function(side_effect="read")
def read_mail(
    account: str,
    mailbox: str = "INBOX",
    message_ids: list[str] | str = "",
) -> dict[str, Any]:
    """Read a short plaintext snippet of 1 to 5 Mail.app messages by id.

    Use this to VERIFY receipts, invoices, or anything that might be
    worth keeping before filing. Never a substitute for list_mail —
    headers first, then peek the uncertain ones. Clamped to 5 ids.
    """
    return _read_mail_impl(account, mailbox, message_ids)


@register_tool_from_function(side_effect="read")
def plan_mail_triage(
    account: str,
    mailbox: str = "INBOX",
    offset: int = 0,
    limit: int = 25,
    peek: bool = True,
) -> dict[str, Any]:
    """One page of conservative filing proposals. Never moves mail.

    Deep-clean primitive: list a bounded page, classify keep-first
    (receipts/finance beat noreply trash), optionally peek bodies of
    uncertain keep-candidates, and return a table the user confirms
    before any batch_move. `next_offset` pages deeper; None means
    this mailbox is done.
    """
    acc = (account or "").strip()
    src = (mailbox or "").strip() or "INBOX"
    page = list_mail(
        account=acc, mailbox=src, limit=limit,
        unread_only=False, offset=offset,
    )
    if not page.get("ok"):
        return _envelope(
            ok=False, items=[], error=page.get("error"),
            timed_out=bool(page.get("timed_out")),
            account=acc, mailbox=src, offset=offset, next_offset=None,
            after_move_offset=0,
        )

    items: list[dict[str, Any]] = []
    peek_ids: list[str] = []
    for msg in page.get("messages") or []:
        filing = classify_filing(
            str(msg.get("sender") or ""), str(msg.get("subject") or ""),
        )
        row = {
            "id": str(msg.get("id") or ""),
            "sender": msg.get("sender"),
            "subject": msg.get("subject"),
            "date": msg.get("date"),
            "category": filing["category"],
            "confidence": filing["confidence"],
            "keep": filing["keep"],
            "destination": filing["destination"],
            "verify": filing["verify"],
            "reason": filing["reason"],
            "snippet": None,
        }
        items.append(row)
        if peek and filing["verify"] and row["id"] and len(peek_ids) < _MAX_PEEK_PER_PAGE:
            peek_ids.append(row["id"])

    if peek and peek_ids:
        peeked = _read_mail_impl(acc, src, peek_ids)
        snippets = {
            m["id"]: m.get("snippet") or ""
            for m in (peeked.get("messages") or [])
        }
        for row in items:
            snippet = snippets.get(row["id"])
            if snippet is None:
                continue
            row["snippet"] = snippet[:_MAX_SNIPPET_OUT]
            header = {
                "category": row["category"],
                "confidence": row["confidence"],
                "keep": row["keep"],
                "destination": row["destination"],
                "verify": row["verify"],
                "reason": row["reason"],
            }
            filing = _prefer_keep(
                header,
                classify_filing(
                    str(row.get("sender") or ""),
                    str(row.get("subject") or ""),
                    snippet,
                ),
            )
            row.update({
                "category": filing["category"],
                "confidence": filing["confidence"],
                "keep": filing["keep"],
                "destination": filing["destination"],
                "verify": False,
                "reason": filing["reason"],
            })

    keep_count = sum(1 for i in items if i["keep"])
    trash_count = sum(1 for i in items if not i["keep"])
    verify_count = sum(1 for i in items if i["verify"] and i["keep"])
    return _envelope(
        ok=True, error=None, items=items, count=len(items),
        account=acc, mailbox=src,
        offset=page.get("offset", offset),
        next_offset=page.get("next_offset"),
        after_move_offset=0,
        keep_count=keep_count, trash_count=trash_count,
        verify_count=verify_count, peeked=len(peek_ids),
    )


def _batch_move_impl(
    account: str,
    source_mailbox: str,
    target_mailbox: str,
    message_ids: Any,
) -> dict[str, Any]:
    """Move many messages in one AppleScript transaction."""
    acc = (account or "").strip()
    src = (source_mailbox or "").strip() or "INBOX"
    dst = (target_mailbox or "").strip()
    ids = _normalize_ids(message_ids)
    if not acc or not dst:
        return _envelope(
            ok=False, moved=False,
            error="account and target_mailbox are required",
        )
    if not ids:
        return _envelope(
            ok=False, moved=False,
            error="message_ids is required; pass the numeric ids from list_mail",
        )
    bad = [i for i in ids if not i.isdigit()]
    if bad:
        return _envelope(
            ok=False, moved=False,
            error=(
                "message_ids must be numeric Mail.app ids from list_mail, "
                f"got {bad!r}"
            ),
        )
    ids = ids[:_MAX_FETCH]
    id_list = ", ".join(ids)
    src_call = _resolve_call("src", acc, src)
    dst_call = _resolve_call("dst", acc, dst)
    script = f'''
    {_AS_RESOLVER}
    tell application "Mail"
        try
            {src_call}
            {dst_call}
            set moved to 0
            set idList to {{{id_list}}}
            repeat with mid in idList
                try
                    set thisId to contents of mid
                    set m to first message of src whose id is thisId
                    move m to dst
                    set moved to moved + 1
                end try
            end repeat
            return "MOVED:" & moved
        on error errMsg
            return "ERROR:" & errMsg
        end try
    end tell
    '''
    res = run_applescript(script, timeout_seconds=10)
    if not res.get("ok"):
        return _envelope(
            ok=False, moved=False,
            error=res.get("error"), timed_out=bool(res.get("timed_out")),
            account=acc, source=src, target=dst, message_ids=ids,
        )
    raw = res.get("raw_output") or ""
    if raw.startswith("MOVED:"):
        try:
            n = int(raw.split(":", 1)[1])
        except ValueError:
            n = 0
        if n != len(ids):
            return _envelope(
                ok=False, moved=n > 0, moved_count=n,
                error=(
                    f"partial move: moved {n} of {len(ids)} messages; "
                    "stop and refresh the inbox before continuing"
                ),
                account=acc, source=src, target=dst, message_ids=ids,
            )
        return _envelope(
            ok=True, moved=True, moved_count=n, error=None,
            account=acc, source=src, target=dst, message_ids=ids,
        )
    err = raw[6:].strip() if raw.startswith("ERROR:") else raw
    return _envelope(
        ok=False, moved=False,
        error=err or "move failed",
        account=acc, source=src, target=dst, message_ids=ids,
    )


@register_tool_from_function(side_effect="external")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="email",
               operation="move_mail",
               summary="move an email in Mail.app")
def move_mail(
    message_id: str,
    account: str,
    source_mailbox: str,
    target_mailbox: str,
) -> dict[str, Any]:
    """Move one Mail.app message by id, account-scoped.

    `message_id` is the `id` field from list_mail — never a shifting
    inbox index. `account` and `source_mailbox` must match the message.
    `target_mailbox` is also under that same account (Archive, Junk,
    Receipts, trash, …). Aliases and Gmail nested paths resolve
    automatically. Prefer batch_move for more than one id.
    """
    result = _batch_move_impl(account, source_mailbox, target_mailbox, [message_id])
    result["message_id"] = str(message_id or "").strip()
    return result


@register_tool_from_function(side_effect="external")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="email",
               operation="batch_move",
               summary="move emails in Mail.app")
def batch_move(
    account: str,
    source_mailbox: str,
    target_mailbox: str,
    message_ids: list[str] | str,
) -> dict[str, Any]:
    """Move many Mail.app messages in one AppleScript transaction.

    `message_ids` is a list (or comma-separated string) of `id` values
    from list_mail. Hard-clamped to 25. `target_mailbox` accepts nested
    paths and aliases (`trash`, `junk`/`spam`, `archive`). Inspect
    `success` and `moved_count` before claiming the filing happened.
    """
    return _batch_move_impl(account, source_mailbox, target_mailbox, message_ids)


@register_tool_from_function(side_effect="external")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="email",
               operation="sweep_mail",
               summary="sweep marketing/GitHub noise out of Mail.app")
def sweep_mail(
    account: str | None = None,
    mailbox: str = "INBOX",
    limit: int = 25,
    dry_run: bool = True,
) -> dict[str, Any]:
    """File obvious inbox noise using bounded list_mail + batch_move.

    Interactive default is dry_run=true: classify only, no moves.
    The scheduled sweeper calls dry_run=false. Auto-files only
    GitHub-Noise (to the GitHub-Noise folder, kept) and
    high-confidence promotional trash. Receipts, finance, personal,
    and uncertain noreply are never auto-filed. Limit is clamped to
    25 per account. Not a deep clean.
    """
    acc = (account or "").strip()
    limit = _coerce_int(limit, 25, lo=1, hi=_MAX_FETCH)
    if acc:
        names = [acc]
    else:
        listed = list_mailboxes()
        if not listed.get("ok"):
            return _envelope(
                ok=False, dry_run=dry_run, candidates=[],
                error=listed.get("error") or "list_mailboxes failed",
                timed_out=bool(listed.get("timed_out")),
            )
        names = [a.get("name", "").strip() for a in listed.get("accounts") or []
                 if a.get("name")]
        if not names:
            return _envelope(
                ok=False, dry_run=dry_run, candidates=[],
                error="no Mail.app accounts found",
            )

    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    timed_out = False
    for name in names:
        fetched = list_mail(
            account=name, mailbox=mailbox, limit=limit, unread_only=False,
        )
        if fetched.get("timed_out"):
            timed_out = True
        if not fetched.get("ok"):
            errors.append(f"{name}: {fetched.get('error') or 'list_mail failed'}")
            continue
        for msg in fetched.get("messages") or []:
            filing = classify_filing(
                str(msg.get("sender") or ""), str(msg.get("subject") or ""),
            )
            # Daily sweep only auto-files high-confidence noise. Receipts,
            # finance, personal, and uncertain noreply stay put.
            target = None
            if filing["category"] == "GitHub-Noise":
                target = "GitHub-Noise"
            elif (
                not filing["keep"]
                and filing["confidence"] == "high"
                and filing["destination"] == "trash"
            ):
                target = "trash"
            candidates.append({
                "id": str(msg.get("id") or ""),
                "account": name,
                "sender": msg.get("sender"),
                "subject": msg.get("subject"),
                "category": filing["category"],
                "keep": filing["keep"],
                "confidence": filing["confidence"],
                "target": target,
            })

    auto = [c for c in candidates if c.get("target") and c.get("id")]
    moved_count = 0
    moved: list[dict[str, Any]] = []
    if not dry_run:
        groups: dict[tuple[str, str], list[str]] = {}
        for c in auto:
            groups.setdefault((c["account"], str(c["target"])), []).append(c["id"])
        for (name, target), ids in groups.items():
            result = _batch_move_impl(name, mailbox, target, ids)
            expected = len(ids)
            actual = int(result.get("moved_count") or 0)
            if not result.get("ok") or actual != expected:
                errors.append(
                    f"{name}->{target}: {result.get('error') or f'batch_move moved {actual} of {expected}'}"
                )
                timed_out = timed_out or bool(result.get("timed_out"))
                continue
            moved_count += actual
            for mid in ids:
                moved.append({"id": mid, "account": name, "target": target})

    err = "; ".join(errors) if errors else None
    if dry_run:
        ok = not errors
    else:
        ok = not errors
    return _envelope(
        ok=ok, error=err, moved_count=moved_count, timed_out=timed_out,
        dry_run=dry_run, accounts_swept=names, candidates=candidates,
        moved=moved, auto_count=len(auto),
    )


@register_tool_from_function(side_effect="write")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="email",
               operation="schedule_inbox_sweeper",
               summary="schedule twice-daily Mail.app inbox sweep")
def schedule_inbox_sweeper(
    morning_hour: int = 8,
    evening_hour: int = 18,
) -> dict[str, Any]:
    """Install a twice-daily cron prompt that runs sweep_mail.

    Default 8:00 AM and 6:00 PM local time. Re-running replaces the
    existing `inbox-sweeper` schedule. Each fire is a fresh agent turn
    that still passes through the tier ladder.
    """
    from jaeger_agent.memory import memory as mem

    h1 = _coerce_int(morning_hour, 8, lo=0, hi=23)
    h2 = _coerce_int(evening_hour, 18, lo=0, hi=23)
    if h1 == h2:
        cron = f"0 {h1} * * *"
    else:
        cron = f"0 {h1},{h2} * * *"
    try:
        row = mem.add_schedule(
            cron_expr=cron, prompt=_SWEEPER_PROMPT, name="inbox-sweeper",
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope(ok=False, scheduled=False, error=str(exc))
    return _envelope(ok=True, scheduled=True, error=None, **row)


__all__ = [
    "send_email",
    "list_mailboxes",
    "list_mail",
    "read_mail",
    "plan_mail_triage",
    "move_mail",
    "batch_move",
    "sweep_mail",
    "schedule_inbox_sweeper",
    "run_applescript",
    "alias_candidates",
    "classify_message",
    "classify_filing",
    "pick_keep_mailbox",
]
