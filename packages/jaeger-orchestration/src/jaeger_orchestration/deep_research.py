"""Autonomous multi-step Deep Research engine & visual report builder.

Clean-room Apache-2.0 implementation (informed by Tongyi DeepResearch Apache-2.0
multi-round search/read/synthesize loops) using pure Python stdlib:
1. Decomposes a topic into focused sub-queries (via ModelPort or deterministic fallback).
2. Runs bounded web searches through an injected ``search_fn``.
3. Reads top source pages through an SSRF-hardened ``safe_fetch_text`` (blocks
   private/loopback/link-local/reserved IPs and redirects).
4. Synthesizes a cited Markdown + standalone Visual HTML report with TOC and
   a ready-to-use ``spinoff_prompt`` for grounded follow-up conversation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import html
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
from typing import Any, Callable
import urllib.parse
import urllib.request
import uuid

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _is_public_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.strip().lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith((".local", ".internal")):
        return False
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return False
    return True


def safe_fetch_text(url: str, *, timeout_s: float = 10.0, max_chars: int = 4000) -> str:
    """Fetch a public HTTP/HTTPS page with SSRF protection and clean HTML stripping."""
    if not _is_public_url(url):
        raise ValueError(f"blocked non-public URL: {url}")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "JaegerAI-DeepResearch/1.0",
            "Accept": "text/html, text/plain, application/xhtml+xml;q=0.9",
        },
        method="GET",
    )
    with opener.open(req, timeout=max(2.0, min(float(timeout_s), 20.0))) as resp:
        raw = resp.read(120_000).decode("utf-8", errors="replace")
    cleaned = _SCRIPT_STYLE_RE.sub(" ", raw)
    cleaned = html.unescape(_TAG_RE.sub(" ", cleaned))
    normalized = " ".join(cleaned.split()).strip()
    return normalized[: max(200, min(int(max_chars), 12_000))]


@dataclass(frozen=True)
class ResearchSource:
    index: int
    title: str
    url: str
    snippet: str
    excerpt: str = ""
    fetched: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchReport:
    report_id: str
    topic: str
    sub_queries: list[str]
    sources: list[ResearchSource]
    markdown: str
    html_report: str
    spinoff_prompt: str
    created_at: float = field(default_factory=time.time)
    elapsed_ms: int = 0
    saved_dir: str = ""

    def to_dict(self, *, include_html: bool = False) -> dict[str, Any]:
        d = {
            "ok": True,
            "report_id": self.report_id,
            "topic": self.topic,
            "sub_queries": list(self.sub_queries),
            "source_count": len(self.sources),
            "sources": [s.to_dict() for s in self.sources],
            "markdown": self.markdown,
            "spinoff_prompt": self.spinoff_prompt,
            "created_at": self.created_at,
            "elapsed_ms": self.elapsed_ms,
            "saved_dir": self.saved_dir,
        }
        if include_html:
            d["html_report"] = self.html_report
        return d


def _render_visual_html(
    *,
    topic: str,
    sub_queries: list[str],
    markdown_body: str,
    sources: list[ResearchSource],
) -> str:
    esc_topic = html.escape(topic)
    toc_items: list[str] = []
    body_html_lines: list[str] = []
    sec_idx = 0
    for raw_line in markdown_body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            sec_idx += 1
            heading = line[3:].strip()
            anchor = f"sec-{sec_idx}"
            toc_items.append(f'<li><a href="#{anchor}">{html.escape(heading)}</a></li>')
            body_html_lines.append(f'<h2 id="{anchor}">{html.escape(heading)}</h2>')
        elif line.startswith("### "):
            body_html_lines.append(f"<h3>{html.escape(line[4:].strip())}</h3>")
        elif line.startswith("- ") or line.startswith("* "):
            body_html_lines.append(f"<li>{html.escape(line[2:].strip())}</li>")
        elif line.startswith("# "):
            continue
        else:
            body_html_lines.append(f"<p>{html.escape(line)}</p>")

    source_cards = "\n".join(
        f'<div class="src"><strong>[{s.index}]</strong> '
        f'<a href="{html.escape(s.url)}" target="_blank" rel="noopener noreferrer">{html.escape(s.title or s.url)}</a>'
        f'<p>{html.escape((s.excerpt or s.snippet)[:280])}</p></div>'
        for s in sources
    )
    query_chips = " ".join(f'<span class="chip">{html.escape(q)}</span>' for q in sub_queries)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{esc_topic} — JaegerAI Deep Research</title>
  <style>
    :root {{ color-scheme: dark light; --bg:#0d1117; --fg:#e6edf3; --card:#161b22; --accent:#58a6ff; --muted:#8b949e; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Inter", sans-serif; background:var(--bg); color:var(--fg); max-width:860px; margin:2rem auto; padding:0 1.25rem; line-height:1.6; }}
    h1 {{ font-size:1.9rem; margin-bottom:0.4rem; }}
    h2 {{ border-bottom:1px solid #30363d; padding-bottom:0.3rem; margin-top:1.8rem; }}
    a {{ color:var(--accent); text-decoration:none; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:0.4rem; margin:0.75rem 0 1.25rem; }}
    .chip {{ background:var(--card); border:1px solid #30363d; border-radius:999px; padding:0.2rem 0.65rem; font-size:0.8rem; color:var(--muted); }}
    .toc {{ background:var(--card); border:1px solid #30363d; border-radius:10px; padding:0.9rem 1.2rem; margin:1.2rem 0; }}
    .src {{ background:var(--card); border:1px solid #30363d; border-radius:8px; padding:0.75rem 1rem; margin:0.6rem 0; }}
    .src p {{ margin:0.35rem 0 0; font-size:0.9rem; color:var(--muted); }}
  </style>
</head>
<body>
  <h1>{esc_topic}</h1>
  <div class="chips">{query_chips}</div>
  <nav class="toc"><strong>Contents</strong><ul>{"".join(toc_items) or "<li><a href='#sources'>Sources</a></li>"}</ul></nav>
  <main>{"".join(body_html_lines)}</main>
  <section id="sources"><h2>Sources ({len(sources)})</h2>{source_cards}</section>
</body>
</html>"""


class DeepResearchEngine:
    """Orchestrates multi-query search, safe source extraction, synthesis, and report storage."""

    def __init__(
        self,
        *,
        search_fn: Callable[[str, int], dict[str, Any]],
        fetch_fn: Callable[[str], str] | None = None,
        model: Any | None = None,
        reports_dir: Path | None = None,
    ) -> None:
        self._search_fn = search_fn
        self._fetch_fn = fetch_fn or safe_fetch_text
        self._model = model
        self._reports_dir = Path(reports_dir).expanduser().resolve() if reports_dir is not None else None

    def _plan_queries(self, topic: str, max_queries: int) -> list[str]:
        cap = max(1, min(int(max_queries or 3), 5))
        if self._model is not None:
            try:
                res = self._model.complete([
                    {
                        "role": "user",
                        "content": (
                            f"Generate {cap} concise, distinct web search queries (one per line, no numbering) "
                            f"to thoroughly research: {topic}"
                        ),
                    }
                ])
                lines = [
                    re.sub(r"^[\d\-\*\.\)\s]+", "", ln).strip()
                    for ln in str(res.get("content") or "").splitlines()
                    if ln.strip()
                ]
                uniq: list[str] = []
                for q in lines:
                    if q and q.lower() not in {u.lower() for u in uniq}:
                        uniq.append(q[:180])
                if uniq:
                    return uniq[:cap]
            except Exception:  # noqa: BLE001
                pass
        base = topic.strip()
        defaults = [base, f"{base} architecture comparison", f"{base} benchmarks limitations"]
        return defaults[:cap]

    def _synthesize_markdown(
        self,
        topic: str,
        sub_queries: list[str],
        sources: list[ResearchSource],
    ) -> str:
        if self._model is not None and sources:
            evidence = "\n\n".join(
                f"[{s.index}] {s.title} ({s.url})\n{(s.excerpt or s.snippet)[:1500]}"
                for s in sources
            )
            prompt = (
                f"Write a structured, deeply factual research report in Markdown on: {topic}\n\n"
                "Use ## section headings (Executive Summary, Key Findings, Tradeoffs & Risks, Recommended Next Steps). "
                "Cite claims inline with [1], [2], etc. using ONLY the provided sources:\n\n"
                f"{evidence}"
            )
            try:
                res = self._model.complete([{"role": "user", "content": prompt}])
                body = str(res.get("content") or "").strip()
                if body:
                    return body
            except Exception:  # noqa: BLE001
                pass

        # Deterministic offline/fallback structured report
        lines = [
            f"# {topic}",
            "",
            "## Executive Summary",
            f"Compiled {len(sources)} source(s) across {len(sub_queries)} research queries for **{topic}**.",
            "",
            "## Key Findings",
        ]
        if not sources:
            lines.append("- No external search results were returned for this query.")
        for s in sources:
            text = (s.excerpt or s.snippet or "No excerpt available.").strip()[:360]
            lines.append(f"- **[{s.index}] {s.title or s.url}**: {text}")
        lines.extend([
            "",
            "## Sources",
            *[f"- [{s.index}] [{s.title or s.url}]({s.url})" for s in sources],
        ])
        return "\n".join(lines).strip()

    def run(
        self,
        topic: str,
        *,
        max_queries: int = 3,
        results_per_query: int = 4,
        max_sources: int = 6,
        fetch_pages: bool = True,
        save: bool = True,
    ) -> ResearchReport:
        clean_topic = (topic or "").strip()
        if not clean_topic or len(clean_topic) > 300:
            raise ValueError("topic must be 1-300 characters")
        t0 = time.monotonic()
        queries = self._plan_queries(clean_topic, max_queries)

        seen_urls: set[str] = set()
        raw_hits: list[dict[str, str]] = []
        per_q = max(1, min(int(results_per_query or 4), 8))
        cap_sources = max(1, min(int(max_sources or 6), 12))

        for q in queries:
            try:
                res = self._search_fn(q, per_q)
            except Exception:  # noqa: BLE001
                continue
            for item in (res.get("results") or []):
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                raw_hits.append({
                    "title": str(item.get("title") or url)[:200],
                    "url": url[:500],
                    "snippet": str(item.get("snippet") or "")[:500],
                })
                if len(raw_hits) >= cap_sources:
                    break
            if len(raw_hits) >= cap_sources:
                break

        sources: list[ResearchSource] = []
        for idx, hit in enumerate(raw_hits, start=1):
            excerpt = ""
            fetched = False
            if fetch_pages:
                try:
                    excerpt = self._fetch_fn(hit["url"])
                    fetched = bool(excerpt)
                except Exception:  # noqa: BLE001
                    excerpt = ""
                    fetched = False
            sources.append(
                ResearchSource(
                    index=idx,
                    title=hit["title"],
                    url=hit["url"],
                    snippet=hit["snippet"],
                    excerpt=excerpt,
                    fetched=fetched,
                )
            )

        md = self._synthesize_markdown(clean_topic, queries, sources)
        visual_html = _render_visual_html(
            topic=clean_topic,
            sub_queries=queries,
            markdown_body=md,
            sources=sources,
        )
        report_id = f"res_{uuid.uuid4().hex[:10]}"
        spinoff = (
            f"Let's discuss the Deep Research report on '{clean_topic}' ({report_id}). "
            f"Key sources: {', '.join(f'[{s.index}] {s.title}' for s in sources[:5])}."
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        saved_dir = ""
        if save and self._reports_dir is not None:
            slug = _SLUG_RE.sub("-", clean_topic.lower()).strip("-")[:48] or "research"
            out_dir = self._reports_dir / f"{slug}-{report_id}"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "report.md").write_text(md, encoding="utf-8")
            (out_dir / "report.html").write_text(visual_html, encoding="utf-8")
            meta = {
                "report_id": report_id,
                "topic": clean_topic,
                "sub_queries": queries,
                "source_count": len(sources),
                "sources": [s.to_dict() for s in sources],
                "spinoff_prompt": spinoff,
                "created_at": time.time(),
                "elapsed_ms": elapsed_ms,
                "html_path": str(out_dir / "report.html"),
                "markdown_path": str(out_dir / "report.md"),
            }
            (out_dir / "report.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            saved_dir = str(out_dir)

        return ResearchReport(
            report_id=report_id,
            topic=clean_topic,
            sub_queries=queries,
            sources=sources,
            markdown=md,
            html_report=visual_html,
            spinoff_prompt=spinoff,
            elapsed_ms=elapsed_ms,
            saved_dir=saved_dir,
        )


def list_research_reports(reports_dir: Path, *, limit: int = 25) -> list[dict[str, Any]]:
    """List saved Deep Research report metadata newest-first."""
    root = Path(reports_dir).expanduser().resolve()
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for meta_file in root.glob("*/report.json"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rows.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda r: float(r.get("created_at") or 0.0), reverse=True)
    return rows[: max(1, min(int(limit or 25), 100))]


__all__ = [
    "DeepResearchEngine",
    "ResearchReport",
    "ResearchSource",
    "list_research_reports",
    "safe_fetch_text",
]
