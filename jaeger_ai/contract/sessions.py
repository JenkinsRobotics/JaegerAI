"""How a session id encodes which framework and which surface made it.

A conversation is created by one of two things — a browser (the WebUI) or a
terminal (the CLI/TUI) — against one of the four frameworks. Both facts have to
survive into the session list, or the sidebar cannot answer "show me Hermes'
conversations" and every row lands under whichever profile happens to be
active.

The id itself carries the framework, because the WebUI runner mints it that
way::

    webui-hermes-6f2a…      browser conversation, Hermes
    webui-openclaw-91cc…    browser conversation, OpenClaw
    roundtable-hermes-4d…   a Roundtable member's leg of a debate

That naming is written in one place and read in another, which is exactly the
kind of fact this package exists to hold. Before it lived here, the gateway
defaulted every session's profile to ``"jaeger"`` — all 65 rows in a live store
claimed to be Jaeger's, including the Hermes and OpenClaw ones — and the
Hermes agent wrote its own rows with ``profile_name`` NULL because it knows
nothing about Jaeger profiles.

Attribution is best-effort by design: a session id minted before this
convention, or by an external tool, resolves to ``None`` rather than being
forced into a bucket it does not belong in. A wrong badge is worse than no
badge, because a wrong one is silently believed.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .frameworks import UnknownFramework, canonical_runtime

#: Where a conversation was started. ``webui`` is a browser, ``cli`` a
#: terminal; the rest are messaging and automation surfaces that also create
#: sessions. These are *surfaces*, never frameworks — a value from this set
#: must never end up in a profile column.
SURFACES: frozenset[str] = frozenset({
    "webui", "cli", "tui", "app", "api", "acp",
    "telegram", "discord", "imessage", "slack", "email", "matrix",
    "cron", "webhook", "mcp", "voice", "kanban", "worker",
})

#: Surfaces that mean "a person typed this in a browser".
BROWSER_SURFACES: frozenset[str] = frozenset({"webui", "app"})

#: Surfaces that mean "a person typed this in a terminal".
TERMINAL_SURFACES: frozenset[str] = frozenset({"cli", "tui", "acp"})

#: Raw ``source`` values seen in the wild that mean something in SURFACES.
_SOURCE_ALIASES = {
    "api_server": "api",
    "web": "webui",
    "web_ui": "webui",
    "terminal": "cli",
    "command_line": "cli",
}

# webui-<runtime>-<hash>, roundtable-<runtime>:<hash>, focus-<runtime>-<hash>.
# Both separators are real: the WebUI runner joins with "-", Roundtable joins
# its per-member legs with ":". Matching only "-" left every Roundtable leg
# unattributed.
_ID_SHAPE = re.compile(r"^(?P<lead>webui|roundtable|focus)-(?P<rt>[a-z0-9]+)[-:]")


@dataclass(frozen=True)
class Attribution:
    """What a session id and its recorded source say about a conversation."""

    runtime: str | None
    """Canonical framework runtime, or ``None`` when the id does not say."""

    surface: str | None
    """Normalised surface, or ``None`` when the source is unrecognised."""

    @property
    def started_in_browser(self) -> bool:
        return self.surface in BROWSER_SURFACES

    @property
    def started_in_terminal(self) -> bool:
        return self.surface in TERMINAL_SURFACES


def native_session_id(runtime: str, key: str) -> str:
    """Mint the session id the WebUI runner uses for a framework conversation.

    The hash keeps the browser's own session key out of the agent-side id while
    staying stable for the same key, so reconnecting resumes the conversation.
    """
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    return f"webui-{canonical_runtime(runtime)}-{digest}"


def normalise_surface(source: object) -> str | None:
    """Map a recorded ``source`` onto :data:`SURFACES`, or ``None``."""
    name = str(source or "").strip().lower()
    name = _SOURCE_ALIASES.get(name, name)
    return name if name in SURFACES else None


def runtime_from_session_id(session_id: object) -> str | None:
    """The framework a session id names, or ``None`` if it does not name one.

    ``None`` is a real answer — an id from before this convention genuinely
    carries no framework, and guessing one would put a wrong badge on a row.
    """
    match = _ID_SHAPE.match(str(session_id or "").strip().lower())
    if match is None:
        return None
    lead, raw = match.group("lead"), match.group("rt")
    try:
        runtime = canonical_runtime(raw)
    except UnknownFramework:
        return None
    # A Roundtable debate delegates to members; the leg belongs to the debate,
    # not to the member that happened to answer it.
    return "roundtable" if lead == "roundtable" else runtime


def attribute(session_id: object, source: object = None,
              profile: object = None,
              store_runtime: object = None) -> Attribution:
    """Work out the framework and surface behind one session row.

    Resolution order, most trustworthy first:

    1. ``profile`` — a value the store already recorded. A store that knows
       the answer is not second-guessed.
    2. the session id, which names the framework for ids minted since this
       convention.
    3. ``store_runtime`` — whose database this row was found in. A row in
       Hermes' own ``state.db`` is a Hermes conversation even when its id is a
       bare hex string from before Jaeger existed; that is a fact about where
       it lives, not a guess.

    Surface comes from ``source`` when recognised. Failing that, an id leading
    with ``webui-`` states its own surface — the prefix means a browser made
    it, whatever the row does or does not record.
    """
    def _known(value: object) -> str | None:
        if value is None:
            return None
        try:
            return canonical_runtime(value)
        except UnknownFramework:
            return None

    runtime = (_known(profile)
               or runtime_from_session_id(session_id)
               or _known(store_runtime))

    surface = normalise_surface(source)
    if surface in (None, "api"):
        match = _ID_SHAPE.match(str(session_id or "").strip().lower())
        if match and match.group("lead") == "webui":
            surface = "webui"
    return Attribution(runtime=runtime, surface=surface)


#: Session ids the Gateway keeps for its own lanes, not for a person's conversation.
INTERNAL_SESSION_IDS = frozenset({"dispatcher", "heartbeat", "kanban_idle", "deepthink"})


def is_conversation_session(session: dict) -> bool:
    """True for a session a person converses in (IDE, WebUI, terminal, app).

    False for the Gateway's internal lanes and for durable-task child sessions,
    which hold machine work (one live one has 14,000 messages) and must not fill
    a sidebar. A projection of the Gateway's sessions filters through this so the
    rule lives in one place.
    """
    sid = str(session.get("session_id") or "")
    if not sid or sid in INTERNAL_SESSION_IDS or sid.startswith("task:"):
        return False
    meta = session.get("metadata") or {}
    return not (meta.get("task_id") or meta.get("parent_session_id") or meta.get("native_session"))


__all__ = [
    "INTERNAL_SESSION_IDS",
    "is_conversation_session",
    "Attribution",
    "BROWSER_SURFACES",
    "SURFACES",
    "TERMINAL_SURFACES",
    "attribute",
    "native_session_id",
    "normalise_surface",
    "runtime_from_session_id",
]
