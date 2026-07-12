"""Is there a newer JROS release? — version parsing + GitHub tag lookup.

Two layers, split so the logic is testable without a network:

  * **pure** — :func:`parse_version`, :func:`is_newer`, :func:`pick_latest`
    do string→tuple comparison; no IO, unit-tested directly.
  * **IO** — :func:`fetch_tags` is the only network call (the GitHub tags
    API); :func:`latest_version` wraps it and swallows "GitHub unreachable"
    into ``None`` so callers can degrade gracefully.

Shared by ``jaeger update`` (what ref to pull) and ``jaeger doctor``
(current-vs-latest readout). The repo is read from the same env var the
installer honours so a fork/mirror works without code edits.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

# Mirror scripts/install.sh: JAEGER_REPO_URL overrides, default is upstream.
# We want "owner/repo", install.sh wants the full git URL — derive ours from
# the env var if it's set, else the known default.
_DEFAULT_REPO = "JenkinsRobotics/JROS"
_TAGS_API = "https://api.github.com/repos/{repo}/tags"


def repo_slug() -> str:
    """``owner/repo`` for the GitHub API, honouring ``JAEGER_REPO_URL``
    (``https://github.com/owner/repo.git`` → ``owner/repo``)."""
    url = os.environ.get("JAEGER_REPO_URL", "").strip()
    if "github.com" in url:
        tail = url.split("github.com", 1)[1].lstrip("/:").removesuffix(".git")
        if tail.count("/") >= 1:
            return "/".join(tail.split("/")[:2])
    return _DEFAULT_REPO


def parse_version(s: str) -> tuple[int, ...]:
    """``'v0.6.0'`` / ``'0.6.0'`` / ``'0.6.0-rc1'`` → ``(0, 6, 0)``.

    Leading ``v`` stripped; split on ``.``; each part contributes its leading
    run of digits (so ``-rc1`` and other suffixes are ignored). An
    unparseable string returns ``()`` — which sorts below every real version,
    so junk tags never win a comparison.
    """
    s = s.strip().lstrip("vV")
    out: list[int] = []
    for part in s.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def is_newer(candidate: str, current: str) -> bool:
    """True iff ``candidate`` is a strictly higher version than ``current``.
    Numeric per-component, so ``0.10.0 > 0.9.0`` (not lexical)."""
    return parse_version(candidate) > parse_version(current)


def pick_latest(tags: list[str]) -> str | None:
    """Highest-version tag, or ``None`` for an empty/all-junk list.
    Unparseable tags are dropped before the max."""
    real = [t for t in tags if parse_version(t)]
    if not real:
        return None
    return max(real, key=parse_version)


def fetch_tags(repo: str | None = None, *, timeout: float = 5.0) -> list[str]:
    """The repo's tag names from the GitHub API (GitHub's order). Raises
    ``urllib.error.URLError`` / ``OSError`` if GitHub is unreachable and
    ``ValueError`` on a malformed body — :func:`latest_version` catches these.
    A ``User-Agent`` is required or the API returns 403."""
    url = _TAGS_API.format(repo=repo or repo_slug())
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "jaeger-update",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https)
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("unexpected tags payload")
    return [item["name"] for item in data
            if isinstance(item, dict) and "name" in item]


def latest_version(repo: str | None = None, *, timeout: float = 5.0) -> str | None:
    """Newest published tag, or ``None`` if GitHub is unreachable or has no
    parseable tags. Never raises — a missing network degrades to 'unknown'."""
    try:
        tags = fetch_tags(repo, timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return pick_latest(tags)


def update_status(repo: str | None = None, *, timeout: float = 5.0) -> dict:
    """``{'current', 'latest', 'available'}`` — the shape the tray menu, the
    Studio banner, and ``doctor`` all want. ``latest`` is ``None`` offline;
    ``available`` is ``True`` only when a strictly-newer tag was found. Never
    raises (safe to call from UI code)."""
    import jaeger_ai
    current = jaeger_ai.__version__
    latest = latest_version(repo, timeout=timeout)
    return {
        "current": current,
        "latest": latest,
        "available": bool(latest and is_newer(latest, current)),
    }


_CACHE_TTL_S = 24 * 3600.0  # once a day is plenty (operator call, 2026-07-11)
_CACHE_NAME = "update_check.json"


def _cache_path(layout: object | None) -> Path | None:
    """``<instance>/run/update_check.json``, or None when there's no
    instance to key the cache to (pre-instance / uninstantiated layout —
    the caller falls back to an uncached check, never a crash)."""
    root = getattr(layout, "root", None)
    return (Path(root) / "run" / _CACHE_NAME) if root else None


def cached_update_status(layout: object | None = None, *, repo: str | None = None,
                         timeout: float = 5.0, ttl_s: float = _CACHE_TTL_S,
                         now: float | None = None) -> dict:
    """:func:`update_status` plus ``notes_url``, with the GitHub lookup
    cached under ``<instance>/run/update_check.json`` for ``ttl_s``
    seconds — so the daily tray poll (app launch + periodic) doesn't
    hit the API every time. Only ``latest`` is cached; ``current`` /
    ``available`` are recomputed live each call against ``jaeger_os.
    __version__`` (cheap, and self-corrects across a restart onto a new
    version without waiting out a stale cache).

    ``layout`` may be None or a layout with no ``root`` (pre-instance) —
    caching is then skipped, not fatal, and every call hits the network
    (rare: onboarding only). ``now`` is an injectable clock for tests.
    Never raises — a bad/corrupt cache file or a write failure both
    degrade to an uncached live check, same as :func:`latest_version`
    degrading a network failure to ``None``."""
    clock = time.time() if now is None else now
    path = _cache_path(layout)
    cached: dict | None = None
    if path is not None:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None
    fresh = (isinstance(cached, dict)
             and isinstance(cached.get("checked_at"), (int, float))
             and (clock - cached["checked_at"]) < ttl_s)
    if fresh:
        latest = cached.get("latest")
    else:
        latest = latest_version(repo, timeout=timeout)
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps({"checked_at": clock, "latest": latest}),
                    encoding="utf-8")
            except OSError:
                pass   # caching is an optimization, not a requirement
    import jaeger_ai
    current = jaeger_ai.__version__
    slug = repo or repo_slug()
    return {
        "current": current,
        "latest": latest,
        "available": bool(latest and is_newer(latest, current)),
        "notes_url": f"https://github.com/{slug}/releases/tag/{latest}" if latest else None,
    }


__all__ = [
    "repo_slug", "parse_version", "is_newer", "pick_latest",
    "fetch_tags", "latest_version", "update_status", "cached_update_status",
]
