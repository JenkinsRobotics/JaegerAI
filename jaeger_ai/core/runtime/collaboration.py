"""How Jaeger works with specialist helpers.

Jaeger always runs as one lead. Specialists are inner helpers: the lead calls
them with ``delegate`` (``call_agent`` is an alias), each runs in a fresh
context from a brief, returns only a result, and the lead answers in its own
voice. Team rooms, @Name hand-offs, and chat transfers have been removed.
A saved ``automation.collaboration_mode`` of ``team`` or ``auto`` is ignored.

The helper contract follows Hermes Agent's ``delegate_task`` (MIT,
NousResearch/hermes-agent ``tools/delegate_tool.py``): fresh child context, a
summary-only return, children never message the user, write memory, schedule
work or approve themselves, and child tools are the parent's tools narrowed,
never widened. No Hermes code is copied here; only the contract is followed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

MODES = ("one_mind", "team", "auto")
DEFAULT = "one_mind"
LABELS = {"one_mind": "One mind", "team": "Team", "auto": "Auto"}
DESCRIPTIONS = {
    "one_mind": "Every message goes to Jaeger. Specialists work as inner helpers and Jaeger answers in one voice.",
    "team": "Team rooms, @Name hand-offs and a roster you can chat with.",
    "auto": "Jaeger decides per task: inner helpers by default, team rooms only when you open a room or @mention an agent.",
}

#: Helper caps (one lead turn). Depth 1: a helper never delegates further.
MAX_DEPTH = 1
MAX_CONCURRENT = 3
MAX_PER_TURN = 6
#: Helper tokens one lead turn may spend across all its helpers. Checked before
#: each new delegation (a running helper is bounded by its timeout instead).
MAX_TOKENS_PER_TURN = 400_000
DEFAULT_TIMEOUT_S = 300
#: A helper result longer than this is saved to a file; the lead gets a preview + path.
RESULT_INLINE_CHARS = 6000

#: Tools a helper never gets, whatever the lead or the profile allow: talking to
#: the user, writing long-term memory, scheduling, delegating further, changing
#: its own permissions or the runtime.
HELPER_DENIED_TOOLS = frozenset({
    # delegation (depth 1)
    "delegate", "call_agent", "run_team", "get_agent_result", "delegate_task", "list_delegate_runtimes",
    "transfer_to_agent",
    # talking to the user / outside
    "clarify", "ask_user", "help_me", "send_message", "send_email", "notify", "text_to_speech", "speak",
    "reply_email", "post_message",
    # long-term memory writes (reads go through the brief's memory excerpt)
    "memory", "remember", "forget", "record_insight", "remember_person", "set_name", "agent_notes",
    "update_soul", "set_persona",
    # scheduling / background work
    "schedule_prompt", "cancel_schedule", "create_event", "cronjob", "task_spawn", "mission_create",
    "goal_create", "background_run",
    # self-approval / runtime control
    "set_autonomy", "set_mode", "approve", "grant_permission",
})
_DENIED_PATTERNS = (
    re.compile(r"^send_"), re.compile(r"(^|_)schedule"), re.compile(r"(^|_)cron"),
    re.compile(r"^remember"), re.compile(r"^notify"), re.compile(r"(^|_)approv"),
)


def helper_may_use(name: str) -> bool:
    n = str(name or "").strip()
    if not n or n in HELPER_DENIED_TOOLS:
        return False
    return not any(p.search(n) for p in _DENIED_PATTERNS)


def helper_tool_grant(lead_tools: Iterable[str]) -> list[str]:
    """The lead's tools a helper may inherit (the profile narrows further)."""
    return sorted({str(t) for t in lead_tools if helper_may_use(str(t))})


def _read_config(config_path: Path | str | None) -> dict[str, Any] | None:
    if not config_path:
        return {}
    path = Path(config_path)
    try:
        if not path.exists():
            return {}
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return raw if isinstance(raw, dict) else None
    except Exception:  # noqa: BLE001
        return None


def configured_mode(config_path: Path | str | None) -> str:
    """Saved ``automation.collaboration_mode``; absent/unreadable/invalid → ``one_mind``.

    Unreadable falls back to one mind (the narrowest: no rooms, no direct
    teammate voices), never to team."""
    raw = _read_config(config_path)
    if not raw:
        return DEFAULT
    automation = raw.get("automation") or {}
    value = automation.get("collaboration_mode") if isinstance(automation, dict) else None
    value = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return value if value in MODES else DEFAULT


def snapshot(mode: str) -> dict[str, Any]:
    return {
        "mode": mode, "label": LABELS.get(mode, mode), "description": DESCRIPTIONS.get(mode, ""),
        "options": [{"id": m, "label": LABELS[m], "description": DESCRIPTIONS[m]} for m in MODES],
        "default": DEFAULT,
        "limits": {"max_depth": MAX_DEPTH, "max_concurrent": MAX_CONCURRENT, "max_per_turn": MAX_PER_TURN,
                   "max_tokens_per_turn": MAX_TOKENS_PER_TURN, "timeout_s": DEFAULT_TIMEOUT_S},
    }


def call_agent_is_delegate(mode: str, *, explicit_mention: bool = False) -> bool:
    """call_agent is always an alias of delegate. Rooms and chat transfers are gone."""
    del mode, explicit_mention
    return True



def helper_prompt(*, display_name: str, specialty: str, brief: str, context: str = "",
                  memory_excerpt: str = "", tools: Iterable[str] | None = None,
                  workspace: str | None = None) -> str:
    """The helper's whole starting context: who it is, the brief, read-only memory."""
    tool_list = ", ".join(sorted(tools or [])) or "none (reason from the brief only)"
    where = f"Working folder (the lead's): {workspace}\n" if workspace else ""
    parts = [
        f"You are {display_name}, an inner helper ({specialty}) of Jaeger. Jaeger is the one assistant "
        "the person talks to; you are part of its thinking, not a separate voice.",
        # Wording note: phrases like "never send ..." read as a privacy request to
        # the sensitivity gate (models/router.classify) and would pin the helper
        # to a local model, so the rules are stated as what is out of scope.
        "Rules: your result goes only to Jaeger. Messaging the person, long-term memory writes, "
        "scheduling, approvals and further delegation are outside your role and not available to you.",
        f"Tools you may use: {tool_list}.",
        where.rstrip("\n"),
        "Brief from Jaeger:\n" + brief.strip(),
    ]
    if context.strip():
        parts.append("Context Jaeger shared:\n" + context.strip())
    if memory_excerpt.strip():
        parts.append("Jaeger's memory (read-only excerpt; you cannot change it):\n" + memory_excerpt.strip())
    parts.append("Return only your result for Jaeger: findings, evidence you actually obtained, and what you "
                 "could not verify. Be concise. Jaeger will answer the person in its own words.")
    return "\n\n".join(p for p in parts if p)


def memory_excerpt(query: str, *, limit_chars: int = 2500) -> str:
    """A bounded, read-only snapshot of the lead's memory relevant to ``query``.

    Facts (key/value store) and the top episodic matches. Never raises; an
    unavailable store yields ``""``."""
    lines: list[str] = []
    try:
        from jaeger_agent.tools import memory as mem

        facts = mem.list_facts() or {}
        rows = facts.get("facts") if isinstance(facts, dict) else None
        if isinstance(rows, dict):
            rows = [{"key": k, "value": v} for k, v in rows.items()]
        for row in (rows or [])[:40]:
            if isinstance(row, dict):
                key, value = row.get("key"), row.get("value")
                subject = row.get("subject")
                if key and value is not None:
                    lines.append(f"- {subject + ': ' if subject else ''}{key} = {str(value)[:200]}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from jaeger_agent.tools import memory as mem

        hits = mem.search_memory(query=query[:500], k=3) or {}
        for hit in (hits.get("results") or hits.get("hits") or [])[:3] if isinstance(hits, dict) else []:
            text = hit.get("text") or hit.get("content") or "" if isinstance(hit, dict) else str(hit)
            if text:
                lines.append(f"- earlier: {' '.join(str(text).split())[:300]}")
    except Exception:  # noqa: BLE001
        pass
    out = "\n".join(lines)
    return out[:limit_chars]


_SECRETISH = re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|bearer|private[_-]?key|ghp_|sk-)")


def scrub_excerpt(text: str) -> str:
    """Drop memory lines that look like credentials before a helper sees them."""
    return "\n".join(line for line in str(text or "").splitlines() if not _SECRETISH.search(line))
