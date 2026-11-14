"""X (Twitter) search — Jaeger's equivalent of Grok's X search tools.

Uses the xAI Responses API ``x_search`` tool. Auth is the Grok CLI
OAuth token in ``~/.grok/auth.json``, or ``XAI_API_KEY`` if one is
present in the process environment / Jaeger secrets file. Values are
never logged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jaeger_os.core.tools.tool_registry import register_tool_from_function

_XAI_RESPONSES = "https://api.x.ai/v1/responses"
_XAI_MODELS = ("grok-4.7", "grok-4", "grok-4-fast-non-reasoning")


def _load_secrets() -> None:
    try:
        from jaeger_ai.core.secrets_env import load_secrets_env
        load_secrets_env()
    except Exception:
        return


def _grok_oauth_token() -> str:
    path = Path.home() / ".grok" / "auth.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                low = str(key).lower()
                if low in {"key", "access_token", "accesstoken", "token"} and isinstance(child, str):
                    token = child.strip()
                    if token:
                        found.append(token)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    return found[0] if found else ""


def _xai_token() -> tuple[str, str]:
    """Return (token, source) without exposing the value."""
    _load_secrets()
    key = (os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY") or "").strip()
    if key:
        return key, "xai_api_key"
    oauth = _grok_oauth_token()
    if oauth:
        return oauth, "grok_oauth"
    return "", ""


def x_search_available() -> bool:
    token, _source = _xai_token()
    return bool(token)


def _extract_text_and_citations(payload: dict[str, Any]) -> tuple[str, list[dict[str, str]], list[dict[str, Any]]]:
    texts: list[str] = []
    citations: list[dict[str, str]] = []
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take_annotations(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            citations.append({
                "url": url,
                "title": str(item.get("title") or "").strip(),
                "type": str(item.get("type") or "").strip(),
            })

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            typ = value.get("type")
            if typ == "custom_tool_call":
                raw_input = value.get("input")
                parsed: Any = raw_input
                if isinstance(raw_input, str):
                    try:
                        parsed = json.loads(raw_input)
                    except ValueError:
                        parsed = raw_input
                calls.append({
                    "name": value.get("name"),
                    "input": parsed,
                    "status": value.get("status"),
                })
            if typ in {"output_text", "text"} and isinstance(value.get("text"), str):
                texts.append(value["text"])
                take_annotations(value.get("annotations"))
            elif typ == "message":
                walk(value.get("content"))
            else:
                for child in value.values():
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload.get("output"))
    return "\n".join(part for part in texts if part.strip()).strip(), citations, calls


def x_search(
    query: str,
    allowed_x_handles: list[str] | None = None,
    excluded_x_handles: list[str] | None = None,
    from_date: str = "",
    to_date: str = "",
) -> dict[str, Any]:
    """Search X (Twitter) via the xAI x_search tool."""
    cleaned = (query or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty query"}
    token, source = _xai_token()
    if not token:
        return {
            "ok": False,
            "error": (
                "X search needs the Grok app login (OAuth in ~/.grok/auth.json) "
                "or XAI_API_KEY in ~/.jaeger/secrets.env"
            ),
        }

    def _handles(values: list[str] | None) -> list[str]:
        out: list[str] = []
        for raw in values or []:
            handle = str(raw or "").strip().lstrip("@")
            if handle and handle not in out:
                out.append(handle)
            if len(out) >= 10:
                break
        return out

    tool: dict[str, Any] = {"type": "x_search"}
    allowed = _handles(allowed_x_handles)
    excluded = _handles(excluded_x_handles)
    if allowed:
        tool["allowed_x_handles"] = allowed
    elif excluded:
        tool["excluded_x_handles"] = excluded
    if from_date and len(from_date.strip()) >= 8:
        tool["from_date"] = from_date.strip()
    if to_date and len(to_date.strip()) >= 8:
        tool["to_date"] = to_date.strip()

    last_error = "no model accepted the request"
    for model in _XAI_MODELS:
        body = {
            "model": model,
            "input": (
                "Search X and return a short summary with a few of the "
                "best citations.\n\n" + cleaned
            ),
            "tools": [tool],
            "max_output_tokens": 800,
        }
        request = Request(
            _XAI_RESPONSES,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=45) as response:  # noqa: S310 — https API
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code in {400, 404}:
                continue
            return {"ok": False, "error": last_error, "auth": source}
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            return {"ok": False, "error": type(exc).__name__, "auth": source}

        if not isinstance(payload, dict):
            last_error = "unexpected response"
            continue
        if payload.get("error"):
            err = payload["error"]
            last_error = str((err.get("message") if isinstance(err, dict) else err) or "xAI error")[:240]
            continue
        text, citations, calls = _extract_text_and_citations(payload)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        details = usage.get("server_side_tool_usage_details") if isinstance(usage, dict) else {}
        return {
            "ok": True,
            "query": cleaned,
            "text": text,
            "citations": citations,
            "searches": calls,
            "auth": source,
            "model": payload.get("model") or model,
            "x_posts_fetched": (details or {}).get("x_posts_fetched"),
            "x_search_calls": (details or {}).get("x_search_calls"),
        }
    return {"ok": False, "error": last_error, "auth": source}


@register_tool_from_function(
    name="x_search",
    side_effect="read",
    toolset="web",
    check_fn=x_search_available,
)
def _t_x_search(
    query: str,
    allowed_x_handles: list[str] | None = None,
    excluded_x_handles: list[str] | None = None,
    from_date: str = "",
    to_date: str = "",
) -> dict:
    """Search X (Twitter) for posts, profiles, or a topic.

    Use this instead of web_search when the question is about discussion
    on X. Optional handle allow/deny lists (no leading @) and YYYY-MM-DD
    dates narrow the results. Returns a short summary plus citation URLs.
    Backed by the signed-in Grok subscription (or XAI_API_KEY if set)."""
    return x_search(
        query=query,
        allowed_x_handles=allowed_x_handles,
        excluded_x_handles=excluded_x_handles,
        from_date=from_date,
        to_date=to_date,
    )
