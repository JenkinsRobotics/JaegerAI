"""Search query preparation.

``sanitize_fts5_query`` is adapted from Hermes-agent
``hermes_state_search.SessionSearchMixin._sanitize_fts5_query`` (simplified
standalone form). ``escape_like`` mirrors ``hermes_state_common.escape_like``.
"""

from __future__ import annotations

import re

MAX_FTS5_QUERY_CHARS = 512

# Characters FTS5's query grammar rejects outside a quoted phrase.
# Assembled via re.escape so backslash cannot be eaten inside the class.
_FTS5_SPECIAL_CHARS = '+{}():"^@/#&|~[]<>,;!?$=\\\''
_FTS5_SPECIAL_RE = re.compile(f"[{re.escape(_FTS5_SPECIAL_CHARS)}]")

_CJK_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\U00020000-\U0002a6df\U0002a700-\U0002b73f"
    r"\U0002b740-\U0002b81f\U0002b820-\U0002ceaf]"
)

# Placeholder markers must not appear in user input; use unlikely sentinels
# rather than NUL bytes so the source file stays valid UTF-8 text.
_PH_PREFIX = "ZZJAEGERQ"
_PH_SUFFIX = "ZZ"


def escape_like(text: str) -> str:
    """Escape SQL LIKE wildcards; pair with ``ESCAPE '\\'``."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def sanitize_fts5_query(query: str) -> str:
    """Sanitize user input for safe use in FTS5 MATCH (or as a clean needle).

    Strategy (Hermes-inspired):
    - Cap length
    - Preserve balanced double-quoted phrases
    - Strip unmatched FTS5-special characters
    - Collapse / drop leading ``*``
    - Trim dangling boolean operators
    - Quote unquoted hyphenated / dotted terms
    """
    query = (query or "")[:MAX_FTS5_QUERY_CHARS]
    if not query.strip():
        return ""

    quoted_parts: list[str] = []
    pieces: list[str] = []
    i = 0
    while i < len(query):
        ch = query[i]
        if ch != '"':
            pieces.append(ch)
            i += 1
            continue
        end = query.find('"', i + 1)
        if end == -1:
            pieces.append(" ")
            i += 1
            continue
        quoted_parts.append(query[i : end + 1])
        pieces.append(f"{_PH_PREFIX}{len(quoted_parts) - 1}{_PH_SUFFIX}")
        i = end + 1

    sanitized = "".join(pieces)
    sanitized = _FTS5_SPECIAL_RE.sub(" ", sanitized)
    if "%" in sanitized and not _contains_cjk(sanitized):
        sanitized = sanitized.replace("%", " ")

    sanitized = re.sub(r"\*+", "*", sanitized)
    sanitized = re.sub(r"(^|\s)\*", r"\1", sanitized)
    sanitized = re.sub(r"(?i)^(AND|OR|NOT)\b\s*", "", sanitized.strip())
    sanitized = re.sub(r"(?i)\s+(AND|OR|NOT)\s*$", "", sanitized.strip())

    def _quote_token(token: str) -> str:
        if not token or token.startswith(_PH_PREFIX):
            return token
        if "-" in token or "." in token:
            if not (token.startswith('"') and token.endswith('"')):
                return f'"{token}"'
        return token

    sanitized = " ".join(_quote_token(tok) for tok in sanitized.split() if tok)

    for idx, part in enumerate(quoted_parts):
        sanitized = sanitized.replace(f"{_PH_PREFIX}{idx}{_PH_SUFFIX}", part)

    return sanitized.strip()


def prepare_search_query(query: str) -> str:
    """Normalize a user query for Jaeger LIKE search (no FTS yet)."""
    cleaned = sanitize_fts5_query(query)
    # LIKE path wants the bare needle, not FTS phrase quotes.
    cleaned = cleaned.replace('"', " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned
