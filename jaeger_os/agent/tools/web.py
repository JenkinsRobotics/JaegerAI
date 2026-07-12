"""Network skills.

  • web_search(query, max_results)  — multi-backend search w/ fallback chain
  • web_fetch(url, max_chars)       — fetch a page, return readable text
  • get_weather(location)           — wttr.in lookup (no API key)

The search tool tries several engines/transports in order. Each
backend is independent: if one is missing its library, broken at
runtime, or rate-limited, the chain falls through to the next. The
final result records *which* backend succeeded so the agent (and
the user) can tell whether they're seeing top-quality results or a
last-ditch fallback.

Backend order (most preferred first):
  1. ``ddgs``                — the modern DuckDuckGo client library
  2. ``duckduckgo_search``   — legacy DuckDuckGo client library
  3. ``ddg_html``            — direct scrape of html.duckduckgo.com
                                using only ``requests`` (a hard dep)
                                plus stdlib HTML parser. No extra deps.
  4. ``wikipedia_api``       — last-resort factual fallback against
                                en.wikipedia.org's public API. Only
                                useful for knowledge queries, not
                                news / time-sensitive lookups, but
                                always available.

Future backends (Brave Search API, SearXNG, Bing) can plug in by
appending to ``_BACKENDS`` — they need the same
``(query, max_results) -> list[result_dict]`` shape, raising on any
failure so the chain advances.
"""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.runtime.tool_interrupt import is_interrupted


# ── Shared result shape ─────────────────────────────────────────────

_Result = dict[str, Any]


def _normalize(title: str | None, url: str | None, snippet: str | None) -> _Result:
    """Backends produce wildly different shapes; collapse to one dict."""
    return {
        "title": (title or "").strip() or None,
        "url": (url or "").strip() or None,
        "snippet": (snippet or "").strip() or None,
    }


# ── Backend 1: ddgs ─────────────────────────────────────────────────


def _backend_ddgs(query: str, max_results: int) -> list[_Result]:
    from ddgs import DDGS  # may raise ImportError
    with DDGS() as ddgs:
        raw = list(ddgs.text(query, max_results=max_results))
    if not raw:
        raise RuntimeError("ddgs returned zero results")
    return [
        _normalize(r.get("title"), r.get("href") or r.get("url"),
                   r.get("body") or r.get("snippet"))
        for r in raw
    ]


# ── Backend 2: duckduckgo_search (legacy) ───────────────────────────


def _backend_duckduckgo_legacy(query: str, max_results: int) -> list[_Result]:
    from duckduckgo_search import DDGS  # may raise ImportError
    with DDGS() as ddgs:
        raw = list(ddgs.text(query, max_results=max_results))
    if not raw:
        raise RuntimeError("duckduckgo_search returned zero results")
    return [
        _normalize(r.get("title"), r.get("href") or r.get("url"),
                   r.get("body") or r.get("snippet"))
        for r in raw
    ]


# ── Backend 3: stdlib DDG HTML scrape ───────────────────────────────


class _DDGHtmlParser(HTMLParser):
    """Pull (title, href, snippet) triples out of html.duckduckgo.com.

    DDG's HTML layout: each result is an ``<a class="result__a">title</a>``
    followed (after some chrome) by ``<a class="result__snippet">snippet</a>``.
    href is a redirect URL like ``//duckduckgo.com/l/?uddg=ENCODED&...``;
    we decode the ``uddg`` query parameter to recover the real target.
    """

    def __init__(self) -> None:
        super().__init__()
        self._results: list[dict[str, str]] = []
        self._mode: str | None = None  # "title" | "snippet" | None
        self._buf: list[str] = []
        self._pending_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_d = {k: (v or "") for k, v in attrs}
        cls = attrs_d.get("class", "")
        if "result__a" in cls:
            self._mode = "title"
            self._buf = []
            self._pending_href = _resolve_ddg_redirect(attrs_d.get("href", ""))
        elif "result__snippet" in cls:
            self._mode = "snippet"
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._mode is None:
            return
        text = html.unescape("".join(self._buf)).strip()
        if self._mode == "title" and self._pending_href:
            self._results.append({
                "title": text, "url": self._pending_href, "snippet": "",
            })
            self._pending_href = None
        elif self._mode == "snippet" and self._results:
            # Attach to the last incomplete result.
            if not self._results[-1].get("snippet"):
                self._results[-1]["snippet"] = text
        self._mode = None
        self._buf = []

    def handle_data(self, data: str) -> None:
        if self._mode is not None:
            self._buf.append(data)


def _resolve_ddg_redirect(href: str) -> str:
    """DDG wraps real URLs in a ``/l/?uddg=...`` redirect; unwrap it."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg", [None])[0]
        if uddg:
            return unquote(uddg)
    except Exception:
        pass
    return href


def _backend_ddg_html(query: str, max_results: int) -> list[_Result]:
    import requests  # hard dep — already on the jaeger extras list
    try:
        import certifi
        verify: Any = certifi.where()
    except ImportError:
        verify = True
    response = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers={
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/123.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=10,
        verify=verify,
    )
    response.raise_for_status()
    parser = _DDGHtmlParser()
    parser.feed(response.text)
    parser.close()
    results = parser._results
    if not results:
        raise RuntimeError("ddg_html scrape parsed zero results")
    return [
        _normalize(r["title"], r["url"], r.get("snippet"))
        for r in results[:max_results]
    ]


# ── Backend 4: Wikipedia API (factual last-resort) ──────────────────


def _backend_wikipedia(query: str, max_results: int) -> list[_Result]:
    import requests
    try:
        import certifi
        verify: Any = certifi.where()
    except ImportError:
        verify = True
    api = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": query,
        "srlimit": str(max_results),
        "utf8": "1",
    }
    response = requests.get(
        api,
        params=params,
        headers={"User-Agent": "Jaeger/1.0 (https://github.com/jenkinsrobotics/jaeger_os)"},
        timeout=10,
        verify=verify,
    )
    response.raise_for_status()
    try:
        data = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"wikipedia returned non-JSON: {exc}") from exc
    hits = (data.get("query") or {}).get("search") or []
    if not hits:
        raise RuntimeError("wikipedia returned zero results")
    results: list[_Result] = []
    for h in hits[:max_results]:
        title = h.get("title") or ""
        snippet = re.sub(r"<[^>]+>", "", h.get("snippet") or "")
        url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
        results.append(_normalize(title, url, html.unescape(snippet)))
    return results


# ── Backend chain ───────────────────────────────────────────────────


_BACKENDS: list[tuple[str, Callable[[str, int], list[_Result]]]] = [
    ("ddgs", _backend_ddgs),
    ("duckduckgo_search", _backend_duckduckgo_legacy),
    ("ddg_html", _backend_ddg_html),
    ("wikipedia_api", _backend_wikipedia),
]


def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Web search with a multi-backend fallback chain.

    Tries each backend in :data:`_BACKENDS` until one returns results.
    The successful backend's name is included in the response under
    ``backend`` so the caller can tell whether they got the high-quality
    DDGS path or a fallback. If ALL backends fail, returns ``{error,
    tried, query}`` with every backend's error string so the user can
    diagnose (missing libs vs. blocked vs. malformed)."""
    cleaned = (query or "").strip()
    if not cleaned:
        return {"error": "empty query"}
    capped = max(1, min(int(max_results or 5), 20))

    errors: list[str] = []
    for name, backend in _BACKENDS:
        try:
            results = backend(cleaned, capped)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        if results:
            return {
                "query": cleaned,
                "results": results,
                "backend": name,
                "tried": errors,  # empty if first backend worked
            }
        errors.append(f"{name}: returned empty list")

    return {
        "error": "all search backends failed",
        "tried": errors,
        "query": cleaned,
    }


# ── web_fetch — read a full page ────────────────────────────────────


class _ReadableText(HTMLParser):
    """Strip a web page down to readable text.

    Drops ``<script>`` / ``<style>`` / ``<head>`` content entirely;
    keeps text from the body. Inserts newlines around block elements so
    the output reads as paragraphs, not one run-on line. Good enough for
    the agent to *read documentation* — not a full reader-mode, but it
    surfaces the prose without the markup."""

    _SKIP = {"script", "style", "head", "noscript", "svg", "nav", "footer"}
    _BLOCK = {"p", "div", "section", "article", "br", "li", "tr", "h1",
              "h2", "h3", "h4", "h5", "h6", "pre", "blockquote"}

    def __init__(self) -> None:
        super().__init__()
        self._depth_skip = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP:
            self._depth_skip += 1
        elif tag in self._BLOCK:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._depth_skip > 0:
            self._depth_skip -= 1
        elif tag in self._BLOCK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._depth_skip == 0:
            text = data.strip()
            if text:
                self._chunks.append(text + " ")

    def text(self) -> str:
        raw = "".join(self._chunks)
        # Collapse runs of blank lines / spaces into something readable.
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n[ \t]+", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def web_fetch(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """Fetch a web page and return its readable text content.

    This is the "research" tool: web_search finds *which* pages are
    relevant; web_fetch *reads* one. Use it to pull a library's docs, a
    Stack Overflow answer, an API reference, a README — anything the
    agent needs to actually understand before writing code.

    HTML is stripped to readable prose (scripts/styles/nav removed).
    JSON and plain-text responses are returned as-is. Output is capped
    at ``max_chars`` (default 8000, hard max 40000) so a huge page
    doesn't blow the context window.

    Returns ``{ok, url, content_type, text, truncated, bytes}`` on
    success or ``{ok: False, error: ...}``."""
    target = (url or "").strip()
    if not target:
        return {"ok": False, "error": "empty url"}
    if not target.lower().startswith(("http://", "https://")):
        target = "https://" + target
    cap = max(500, min(int(max_chars or 8000), 40000))

    try:
        import requests
    except ImportError as exc:
        return {"ok": False, "url": target,
                "error": f"requests not installed: {exc}"}
    try:
        import certifi
        verify: Any = certifi.where()
    except ImportError:
        verify = True

    # Fetch the body in chunks (stream=True) rather than one blocking read,
    # so a slow or huge page can be abandoned the moment the turn is
    # cancelled instead of running to completion. 5 MB hard cap on the raw
    # body — well past any page worth reading, and a backstop on a server
    # that never stops sending.
    RAW_CAP = 5_000_000
    resp = None
    body = bytearray()
    try:
        resp = requests.get(
            target,
            headers={
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X "
                               "10_15_7) AppleWebKit/537.36 (KHTML, like "
                               "Gecko) Chrome/123.0 Safari/537.36"),
                "Accept": "text/html,application/xhtml+xml,application/"
                          "json,text/plain;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
            verify=verify,
            stream=True,
        )
        resp.raise_for_status()
        for chunk in resp.iter_content(chunk_size=16384):
            if is_interrupted():
                return {"ok": False, "url": target, "interrupted": True,
                        "error": "web_fetch interrupted by user"}
            if chunk:
                body.extend(chunk)
                if len(body) >= RAW_CAP:
                    break
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": target,
                "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

    content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
    raw = bytes(body).decode(resp.encoding or "utf-8", errors="replace")

    if "html" in content_type or (not content_type and "<html" in raw[:500].lower()):
        parser = _ReadableText()
        try:
            parser.feed(raw)
            parser.close()
            text = parser.text()
        except Exception:  # noqa: BLE001
            # Parsing blew up — fall back to a crude tag strip.
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    else:
        # JSON / plain text / markdown — return as-is.
        text = raw

    truncated = len(text) > cap
    return {
        "ok": True,
        "url": target,
        "content_type": content_type or "unknown",
        "text": text[:cap],
        "truncated": truncated,
        "bytes": len(body),
    }


# ── Weather (unchanged) ─────────────────────────────────────────────


def get_weather(location: str) -> dict[str, Any]:
    """Look up current weather at a named location via wttr.in (no API key)."""
    clean = location.strip()
    if not clean:
        return {"error": "empty location"}
    try:
        import certifi
        import requests
    except ImportError as exc:
        return {"error": f"requests/certifi missing: {exc}", "location": clean}
    fmt = "%C+%t+(feels+%f),+humidity+%h,+wind+%w"
    try:
        response = requests.get(
            f"https://wttr.in/{clean}",
            params={"format": fmt},
            headers={"User-Agent": "Jaeger/1.0"},
            timeout=10,
            verify=certifi.where(),
        )
        text = response.text.strip()
    except Exception as exc:
        return {"error": str(exc), "location": clean}
    if not text or text.lower().startswith("unknown location") or "<html" in text.lower():
        return {"error": "unknown location", "location": clean}
    pretty = re.sub(r"\s+", " ", text.replace("+", " ")).strip()
    return {"location": clean, "weather": pretty}


# ── Agent-tool wrappers (migrated from main.py::_register_builtins) ──


@register_tool_from_function(name="web_search", side_effect="read")
def _t_web_search(query: str, max_results: int = 5) -> dict:
    """Web search (multi-backend, no API key). Returns titles + URLs
    + snippets. Use this to FIND relevant pages, then web_extract to
    actually READ one."""
    return web_search(query=query, max_results=max_results)


@register_tool_from_function(name="web_extract", side_effect="read")
def _t_web_extract(url: str, max_chars: int = 8000) -> dict:
    """Fetch a web page and return its readable text. This is the
    research tool — web_search finds which pages matter, web_extract
    reads one. Use it to pull library docs, API references, Stack
    Overflow answers, READMEs — anything you need to understand
    before writing code for an unfamiliar task."""
    return web_fetch(url=url, max_chars=max_chars)


@register_tool_from_function(name="get_weather", side_effect="read")
def _t_get_weather(location: str) -> dict:
    """Look up current weather via wttr.in (no API key)."""
    return get_weather(location=location)
