"""`@file` / `@url` reference expansion for user input (audit A4).

Lets a user pull a file or a web page straight into a turn — type
`@src/main.py` or `@https://example.com/doc` and the referenced content
is inlined for the agent, instead of the user having to ask it to call
`read_file` / `web_fetch` (an extra round-trip for something they
already have the path to).

The original message is left unchanged; each reference's content is
appended as a clearly-labelled block. File reads go through
`_resolve_read`, so a `@~/.ssh/id_rsa` is refused by the A5 guard. A
reference that can't be resolved is noted inline — it never fails the
turn.
"""

from __future__ import annotations

import re
from typing import Callable

# @token — `@` at start-of-string or after whitespace (so an email
# address like name@host is never matched), then a non-whitespace run.
_REF_RE = re.compile(r"(?:^|(?<=\s))@(\S+)")

# Trailing punctuation a user naturally types right after a reference.
_TRAILING = ".,;:!?)\"'"

# Per-reference content cap — keep a huge file from blowing the window.
_MAX_CHARS = 20_000


def _default_read_file(path: str) -> str:
    from jaeger_os.agent.tools._common import _resolve_read

    p = _resolve_read(path)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(path)
    return p.read_text(encoding="utf-8", errors="replace")


def _default_fetch_url(url: str) -> str:
    from jaeger_os.agent.tools.web import web_fetch

    res = web_fetch(url)
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "fetch failed")
    return res.get("text") or ""


def expand_references(
    text: str,
    *,
    read_file: Callable[[str], str] | None = None,
    fetch_url: Callable[[str], str] | None = None,
) -> str:
    """Expand `@file` / `@url` references in ``text``.

    Returns ``text`` unchanged when it carries no references; otherwise
    returns the original message followed by one labelled block per
    reference. A reference that can't be resolved is noted inline rather
    than raising — the turn always proceeds."""
    if not text or "@" not in text:
        return text
    _read = read_file or _default_read_file
    _fetch = fetch_url or _default_fetch_url

    # Collect distinct references in first-seen order.
    seen: list[str] = []
    for m in _REF_RE.finditer(text):
        tok = m.group(1).rstrip(_TRAILING)
        if tok and tok not in seen:
            seen.append(tok)
    if not seen:
        return text

    blocks: list[str] = []
    for ref in seen:
        is_url = ref.lower().startswith(("http://", "https://"))
        try:
            content = _fetch(ref) if is_url else _read(ref)
        except Exception as exc:  # noqa: BLE001 — surfaced inline, not raised
            blocks.append(
                f"[@{ref} — could not read: {type(exc).__name__}: {exc}]"
            )
            continue
        content = content or ""
        truncated = len(content) > _MAX_CHARS
        kind = "url" if is_url else "file"
        note = "  (truncated)" if truncated else ""
        blocks.append(
            f"[referenced {kind}: @{ref}{note}]\n```\n"
            f"{content[:_MAX_CHARS]}\n```"
        )

    return text + "\n\n" + "\n\n".join(blocks)


__all__ = ["expand_references"]
