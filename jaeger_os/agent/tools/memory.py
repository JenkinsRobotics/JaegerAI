"""Memory skills — k/v store + semantic search.

  • remember / recall / forget / list_facts  — atomic k/v in facts.json
  • search_memory(query, k)                  — semantic search over episodic.jsonl

The k/v ops are jaeger-native (instance-scoped facts.json). search_memory
is new in this parity port — uses the same shape as pydantic_ai's
search_memory, backed by the per-instance episodic log.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.memory import memory as mem


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
