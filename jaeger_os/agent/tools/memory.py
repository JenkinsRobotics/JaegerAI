"""Memory skills — k/v store + semantic search.

  • remember / recall / forget / list_facts  — atomic k/v in facts.json
  • search_memory(query, k)                  — semantic search over episodic.jsonl

The k/v ops are jaeger-native (instance-scoped facts.json). search_memory
is new in this parity port — uses the same shape as pydantic_ai's
search_memory, backed by the per-instance episodic log.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.agent.schemas.tool_registry import register_tool_from_function
from jaeger_os.core.memory import memory as mem
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier


# ---------------------------------------------------------------------------
# K/V memory
# ---------------------------------------------------------------------------
def remember(key: str, value: str, category: str = "") -> dict[str, Any]:
    """Store a fact in the instance's persistent memory.

    Call proactively when the user shares a preference, identity fact,
    plan, or anything they might recall later. Acknowledging in free-text
    without calling this is forbidden — it lies.

    ``category`` groups the fact so memory stays organised — use a short
    label like ``contacts``, ``preferences``, ``projects``, ``schedule``.
    Omit it for a miscellaneous fact (lands in ``general``)."""
    cat = (category or "").strip().lower() or None
    mem.remember(key, value, category=cat)
    return {"remembered": True, "key": key, "value": value,
            "category": cat or "general"}


def recall(key: str) -> dict[str, Any]:
    """Retrieve a fact previously stored via remember().

    Call BEFORE answering questions about what the user said earlier.
    The persisted store is the source of truth across sessions; short-
    term context is not. Fuzzy matching is supported."""
    value = mem.recall(key)
    if value is None:
        return {"found": False, "key": key}
    return {"found": True, "key": key, "value": value}


def forget(key: str) -> dict[str, Any]:
    """Remove a stored fact by key."""
    existed = mem.forget(key)
    return {"forgotten": existed, "key": key}


def list_facts() -> dict[str, Any]:
    """List every fact in instance memory, grouped by category.

    Returns the flat ``facts`` map plus ``by_category`` —
    ``{category: {key: value}}`` — so the organised view (contacts,
    preferences, …) is available without a second call."""
    return {
        "facts": mem.list_facts(),
        "by_category": mem.list_facts_by_category(),
    }


# ---------------------------------------------------------------------------
# Semantic search over the episodic log
# ---------------------------------------------------------------------------
def search_memory(query: str, k: int = 5) -> dict[str, Any]:
    """Semantic search over the instance's episodic conversation log.

    Use when `recall` misses — natural questions like "what did we talk
    about yesterday?" or "what's that thing I mentioned about the
    printer?". Returns up to k past turns with cosine-similarity scores.

    Index is built lazily on first call from episodic.jsonl and cached
    on disk; subsequent calls reuse the cache until the log changes."""
    clean = (query or "").strip()
    if not clean:
        return {"found": 0, "results": []}
    try:
        hits = mem.search_memory(clean, k=k)
    except AttributeError:
        # Older memory module without semantic search — graceful fall-through.
        return {"found": 0, "results": [], "error": "search_memory not available in this build"}
    return {"found": len(hits), "query": clean, "results": hits}


# ---------------------------------------------------------------------------
# Consolidated memory tool — one tool, every memory operation
# ---------------------------------------------------------------------------
def memory(action: str, key: str = "", value: str = "",
           query: str = "", category: str = "") -> dict[str, Any]:
    """One tool for the agent's whole memory. ``action`` selects the op:

      - ``remember`` — store a fact; needs ``key`` + ``value`` (optional
        ``category`` like 'contacts', 'preferences', 'projects').
      - ``recall``   — look up a fact; needs ``key`` (fuzzy match ok).
      - ``forget``   — delete a fact; needs ``key``.
      - ``list``     — every stored fact, grouped by category.
      - ``search``   — semantic search over past conversation; needs ``query``.

    Consolidates remember/recall/forget/list_facts/search_memory so the
    model routes one memory tool, not five."""
    act = (action or "").strip().lower()
    if act in ("remember", "store", "save", "add", "set"):
        if not key or not value:
            return {"ok": False, "error": "remember needs both key and value"}
        return {"ok": True, **remember(key, value, category)}
    if act in ("recall", "get", "lookup", "retrieve"):
        if not key:
            return {"ok": False, "error": "recall needs a key"}
        return {"ok": True, **recall(key)}
    if act in ("forget", "delete", "remove"):
        if not key:
            return {"ok": False, "error": "forget needs a key"}
        return {"ok": True, **forget(key)}
    if act in ("list", "list_facts", "all", "show"):
        return {"ok": True, **list_facts()}
    if act in ("search", "find", "search_memory"):
        return {"ok": True, **search_memory(query or key)}
    return {"ok": False,
            "error": f"unknown memory action {action!r} — use one of: "
                     "remember, recall, forget, list, search"}


# ---------------------------------------------------------------------------
# Agent-facing tool wrappers (migrated from main.py::_register_builtins).
# Private ``_t_*`` names + explicit ``name=`` override so the gated tool never
# collides with the ungated logic fn above (used by internal callers).
# ---------------------------------------------------------------------------
@register_tool_from_function(name="remember")
def _t_remember(key: str, value: str, category: str = "") -> dict:
    """MANDATORY when the user states a preference, identity fact,
    plan, or anything they might recall later. Call this proactively
    — do not just acknowledge "OK, I'll remember" in text. Pick a
    descriptive snake_case key.

    Set `category` to keep memory organised — a short label like
    `contacts`, `preferences`, `projects`, `schedule`; omit it for a
    miscellaneous fact. Examples: "my favorite color is teal"
    (preferences), "Sara's number is 555-0142" (contacts), "I'll be
    in Tokyo next week" (schedule). For YOUR OWN name use set_name,
    not this."""
    return remember(key=key, value=value, category=category)


@register_tool_from_function(name="recall", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="memory", operation="recall",
               summary="recall a fact by key")
def _t_recall(key: str) -> dict:
    """MANDATORY when the user asks about something they told you
    earlier ("what did I say my…", "do you remember…", "what's my
    favorite X", "what video length do I prefer?"). Call BEFORE
    answering — the persisted store is the source of truth.
    Fuzzy match supported, so close-but-not-exact keys still hit."""
    return recall(key=key)


@register_tool_from_function(name="forget")
def _t_forget(key: str) -> dict:
    """MANDATORY when the user asks to remove a stored fact
    ("forget my X", "remove my X preference", "I changed my mind
    about X"). Call this — don't just acknowledge in text."""
    return forget(key=key)


@register_tool_from_function(name="list_facts", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="memory", operation="list_facts",
               summary="list every stored fact")
def _t_list_facts() -> dict:
    """MANDATORY for open-ended "what do you know about me?" or
    "what have I told you?" questions. Returns the full k/v store.
    Use this before falling back to free-text 'I don't know'."""
    return list_facts()


@register_tool_from_function(name="search_memory", side_effect="read")
def _t_search_memory(query: str, k: int = 5) -> dict:
    """Semantic search over this instance's episodic conversation log.
    Use when `recall` (exact key) misses — e.g. "what did we talk
    about yesterday?", "did I tell you about my dog?". Returns top-k
    past turns with cosine-similarity scores."""
    return search_memory(query=query, k=k)


@register_tool_from_function(name="memory")
def _t_memory(action: str, key: str = "", value: str = "",
              query: str = "", category: str = "") -> dict:
    """The agent's persistent memory — one tool, action-dispatched.
    ``action`` ∈ remember / recall / forget / list / search.
    ``remember`` takes key+value (and optional category);
    ``recall`` / ``forget`` take key; ``search`` takes query.
    See ``describe_tool("memory")`` for the full when-to-call
    contract — the prompt's MANDATORY_TOOL_RULES section also
    covers it."""
    return memory(action=action, key=key, value=value,
                  query=query, category=category)
