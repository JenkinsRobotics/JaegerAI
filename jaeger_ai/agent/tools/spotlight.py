"""Spotlight — one tool, ``spotlight_search``, over ``mdfind`` (+ ``mdls``
for per-hit metadata).

READ_ONLY: this is a search, nothing is written or changed. It is the
FIRST move for "find my X" / "where's the Y I made last week" — faster
and more accurate than walking directories with search_files (which
greps CONTENTS under the sandbox only), because Spotlight already has
the whole disk indexed by real metadata (kind, dates, screenshot flag)
rather than filename guessing.

Query forms (raw ``kMDItem*`` predicates, joined with mdfind's query
language — the same predicate language Spotlight itself uses):

  * ``kind="screenshot"`` -> ``kMDItemIsScreenCapture = 1``
  * ``kind="image"``      -> ``kMDItemContentTypeTree = "public.image"``
  * ``kind="pdf"``        -> ``kMDItemContentTypeTree = "com.adobe.pdf"``
  * ``kind="document"``   -> ``kMDItemContentTypeTree = "public.content"``
  * ``kind="app"``        -> ``kMDItemContentTypeTree = "com.apple.application-bundle"``
  * ``since="today"``     -> ``kMDItemFSContentChangeDate >= $time.today(0)``
  * ``since="week"``      -> ``kMDItemFSContentChangeDate >= $time.today(-7)``
  * ``since="month"``     -> ``kMDItemFSContentChangeDate >= $time.today(-30)``
  * ``since="<N>"`` (a bare integer string) -> the last N days.
  * free-text ``query``   -> matched against filename OR content:
    ``kMDItemDisplayName == "*<query>*"cd || kMDItemTextContent == "*<query>*"cd``

All present predicates are AND-ed together. Each hit is then enriched
via one ``mdls`` call (display name, content type, size, modified date)
so the agent doesn't need a second tool round-trip per file — capped at
``limit`` to bound the number of ``mdls`` subprocess calls.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_MDFIND_S = 15
_TIMEOUT_MDLS_S = 5
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 200

_KIND_QUERIES: dict[str, str] = {
    "screenshot": "kMDItemIsScreenCapture = 1",
    "image": 'kMDItemContentTypeTree = "public.image"',
    "pdf": 'kMDItemContentTypeTree = "com.adobe.pdf"',
    "document": 'kMDItemContentTypeTree = "public.content"',
    "app": 'kMDItemContentTypeTree = "com.apple.application-bundle"',
}

_MDLS_FIELDS = (
    "kMDItemDisplayName", "kMDItemContentType",
    "kMDItemFSSize", "kMDItemContentModificationDate",
)


def _escape_query_literal(text: str) -> str:
    """Escape double-quotes for a value embedded inside an mdfind
    ``"..."`` string literal."""
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def _since_predicate(since: str) -> str | None:
    tag = (since or "").strip().lower()
    if not tag:
        return None
    days_by_tag = {"today": 0, "yesterday": 1, "week": 7, "this week": 7, "month": 30}
    if tag in days_by_tag:
        return f"kMDItemFSContentChangeDate >= $time.today(-{days_by_tag[tag]})"
    if tag.isdigit():
        return f"kMDItemFSContentChangeDate >= $time.today(-{int(tag)})"
    return None


def _build_query(query: str, kind: str | None, since: str | None) -> str:
    predicates: list[str] = []
    if kind:
        kind_pred = _KIND_QUERIES.get(kind.strip().lower())
        if kind_pred:
            predicates.append(kind_pred)
    since_pred = _since_predicate(since or "")
    if since_pred:
        predicates.append(since_pred)
    q = (query or "").strip()
    if q:
        escaped = _escape_query_literal(q)
        predicates.append(f'(kMDItemDisplayName == "*{escaped}*"cd || '
                           f'kMDItemTextContent == "*{escaped}*"cd)')
    return " && ".join(predicates)


def _mdls_metadata(path: str) -> dict[str, Any]:
    """One ``mdls`` round-trip for the fields in ``_MDLS_FIELDS``.
    Best-effort — a failed/partial probe returns whatever it got."""
    args = ["mdls"]
    for f in _MDLS_FIELDS:
        args += ["-name", f]
    args.append(path)
    try:
        out = subprocess.run(args, check=False, capture_output=True, text=True,
                              timeout=_TIMEOUT_MDLS_S)
    except Exception:  # noqa: BLE001 — metadata is a bonus, never fatal
        return {}
    if out.returncode != 0:
        return {}
    meta: dict[str, Any] = {}
    for line in out.stdout.splitlines():
        if " = " not in line:
            continue
        key, _, value = line.partition(" = ")
        key = key.strip()
        value = value.strip().strip('"')
        if value in ("(null)", ""):
            continue
        meta[key] = value
    return meta


def spotlight_search(
    query: str = "", kind: str | None = None, since: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search the whole Mac by metadata via ``mdfind`` — filenames,
    content, kind, and dates, indexed by Spotlight (not a directory
    walk). ``query`` is free text (optional if ``kind``/``since``
    narrow enough on their own); ``kind`` is one of
    screenshot/image/pdf/document/app; ``since`` is
    today/yesterday/week/month or a bare number of days. Results are
    capped at ``limit`` (default 20, max 200) and each carries basic
    metadata (display name, content type, size, modified date) from a
    follow-up ``mdls`` probe.
    """
    if platform.system() != "Darwin":
        return {"searched": False,
                 "error": f"Spotlight (mdfind) is only available on macOS (got {platform.system()})"}
    if shutil.which("mdfind") is None:
        return {"searched": False, "error": "mdfind not on PATH (macOS-only utility)"}

    predicate = _build_query(query, kind, since)
    if not predicate:
        return {"searched": False,
                 "error": "empty search — pass query and/or kind and/or since"}

    cap = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
    try:
        out = subprocess.run(
            ["mdfind", predicate], check=False, capture_output=True, text=True,
            timeout=_TIMEOUT_MDFIND_S,
        )
    except subprocess.TimeoutExpired:
        return {"searched": False, "error": f"mdfind timed out after {_TIMEOUT_MDFIND_S}s"}
    except Exception as exc:  # noqa: BLE001
        return {"searched": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"searched": False,
                 "error": (out.stderr or out.stdout or "mdfind failed").strip()}

    paths = [p for p in out.stdout.splitlines() if p.strip()]
    truncated = len(paths) > cap
    paths = paths[:cap]

    results = []
    for path in paths:
        meta = _mdls_metadata(path)
        results.append({
            "path": path,
            "name": meta.get("kMDItemDisplayName"),
            "content_type": meta.get("kMDItemContentType"),
            "size": meta.get("kMDItemFSSize"),
            "modified": meta.get("kMDItemContentModificationDate"),
        })
    return {
        "searched": True, "query": predicate, "count": len(results),
        "truncated": truncated, "results": results,
    }


# ── Agent-facing tool wrapper ────────────────────────────────────────


@register_tool_from_function(name="spotlight_search", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="spotlight", operation="spotlight_search",
               summary="search the Mac by Spotlight metadata")
def _t_spotlight_search(
    query: str = "", kind: str | None = None, since: str | None = None,
    limit: int = 20,
) -> dict:
    """Find files ANYWHERE on this Mac by Spotlight metadata — the
    FIRST tool for "find my X" / "where's the Y from last week", faster
    and broader than search_files (which only greps content under the
    sandbox). `kind` narrows to a category: screenshot, image, pdf,
    document, app. `since` narrows by recency: today, yesterday, week,
    month, or a bare number of days. `query` is free text matched
    against filename or content. Combine freely — e.g. kind="screenshot",
    since="week" finds this week's screenshots with no query text at
    all. Returns {results: [{path, name, content_type, size, modified}]}
    capped at `limit` (default 20). Pairs with move_file/copy_file:
    find it here, then move/copy the path it returns."""
    return spotlight_search(query=query, kind=kind, since=since, limit=limit)


__all__ = ["spotlight_search"]
