"""Multi-backend web search tool for jaeger-tools (stdlib-only, zero API key required by default).

Provider resolution order:
1. Tavily (`TAVILY_API_KEY`) — structured web results
2. Brave Search (`BRAVE_API_KEY`) — structured web results
3. Self-hosted SearXNG (`SEARXNG_URL`) — private local/LAN metasearch
4. DuckDuckGo HTML fallback (`https://html.duckduckgo.com/html/`) — zero-config default

All network calls use bounded timeouts, refuse ambient secret leaks, and never retry
deterministic 401/403/429 responses.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

__all__ = ["web_search"]

_DDG_LINK_RE = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_DDG_SNIP_RE = re.compile(
    r'<(?:a|div)[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(?P<snip>.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(raw: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", raw or "")).split())


def _unwrap_ddg_href(href: str) -> str:
    raw = html.unescape(href or "").strip()
    if raw.startswith("//"):
        raw = "https:" + raw
    parsed = urllib.parse.urlsplit(raw)
    if "duckduckgo.com" in (parsed.hostname or "") and parsed.path.startswith("/l/"):
        qs = urllib.parse.parse_qs(parsed.query)
        target = (qs.get("uddg") or [""])[0]
        if target:
            return target
    return raw


def _search_tavily(query: str, limit: int, api_key: str, timeout_s: float) -> dict[str, Any]:
    payload = json.dumps({
        "api_key": api_key,
        "query": query,
        "max_results": limit,
        "include_answer": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read(250_000).decode("utf-8", errors="replace"))
    results = [
        {
            "title": str(r.get("title") or "")[:200],
            "url": str(r.get("url") or "")[:500],
            "snippet": str(r.get("content") or "")[:400],
        }
        for r in (data.get("results") or [])[:limit]
        if isinstance(r, dict)
    ]
    return {"provider": "tavily", "query": query, "results": results}


def _search_brave(query: str, limit: int, api_key: str, timeout_s: float) -> dict[str, Any]:
    qs = urllib.parse.urlencode({"q": query, "count": limit})
    req = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{qs}",
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read(250_000).decode("utf-8", errors="replace"))
    web_rows = ((data.get("web") or {}).get("results") or [])[:limit]
    results = [
        {
            "title": str(r.get("title") or "")[:200],
            "url": str(r.get("url") or "")[:500],
            "snippet": str(r.get("description") or "")[:400],
        }
        for r in web_rows
        if isinstance(r, dict)
    ]
    return {"provider": "brave", "query": query, "results": results}


def _search_searxng(query: str, limit: int, base_url: str, timeout_s: float) -> dict[str, Any]:
    qs = urllib.parse.urlencode({"q": query, "format": "json"})
    url = f"{base_url.rstrip('/')}/search?{qs}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "JaegerAI/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read(250_000).decode("utf-8", errors="replace"))
    results = [
        {
            "title": str(r.get("title") or "")[:200],
            "url": str(r.get("url") or "")[:500],
            "snippet": str(r.get("content") or "")[:400],
        }
        for r in (data.get("results") or [])[:limit]
        if isinstance(r, dict)
    ]
    return {"provider": "searxng", "query": query, "results": results}


def _parse_ddg_html(body: str, limit: int) -> list[dict[str, str]]:
    links = list(_DDG_LINK_RE.finditer(body))
    snips = list(_DDG_SNIP_RE.finditer(body))
    results: list[dict[str, str]] = []
    for idx, m in enumerate(links[:limit]):
        url = _unwrap_ddg_href(m.group("href"))
        title = _clean_html(m.group("title"))[:200]
        snippet = _clean_html(snips[idx].group("snip"))[:400] if idx < len(snips) else ""
        if url and title:
            results.append({"title": title, "url": url, "snippet": snippet})
    return results


def _search_duckduckgo(query: str, limit: int, timeout_s: float) -> dict[str, Any]:
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) JaegerAI/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read(300_000).decode("utf-8", errors="replace")
    return {"provider": "duckduckgo", "query": query, "results": _parse_ddg_html(raw, limit)}


def web_search(
    query: str,
    *,
    limit: int = 5,
    provider: str = "auto",
    timeout_s: float = 12.0,
) -> dict[str, Any]:
    """Run a bounded web search using configured API provider or zero-config DuckDuckGo."""
    cleaned = (query or "").strip()
    if not cleaned or len(cleaned) > 400:
        raise ValueError("query must be 1-400 characters")
    cap = max(1, min(int(limit or 5), 10))
    timeout = max(2.0, min(float(timeout_s or 12.0), 30.0))
    pref = (provider or "auto").strip().lower()

    tavily_key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    brave_key = (os.environ.get("BRAVE_API_KEY") or "").strip()
    searx_url = (os.environ.get("SEARXNG_URL") or "").strip()

    try:
        if pref == "tavily" or (pref == "auto" and tavily_key):
            if not tavily_key:
                raise ValueError("TAVILY_API_KEY is not configured")
            return _search_tavily(cleaned, cap, tavily_key, timeout)
        if pref == "brave" or (pref == "auto" and brave_key):
            if not brave_key:
                raise ValueError("BRAVE_API_KEY is not configured")
            return _search_brave(cleaned, cap, brave_key, timeout)
        if pref == "searxng" or (pref == "auto" and searx_url):
            if not searx_url:
                raise ValueError("SEARXNG_URL is not configured")
            return _search_searxng(cleaned, cap, searx_url, timeout)
        return _search_duckduckgo(cleaned, cap, timeout)
    except urllib.error.HTTPError as exc:
        hint = " Do not retry immediately." if exc.code in (401, 403, 429) else ""
        raise RuntimeError(f"Web search HTTP {exc.code}: {exc.reason}.{hint}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Web search network error: {exc}") from exc
