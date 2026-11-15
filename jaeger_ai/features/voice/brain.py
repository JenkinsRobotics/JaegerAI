"""The voice brain: the small local model that answers spoken conversation.

Voice turns are ordinary Gateway turns on the current session (same history,
tools and Autonomy). When the executive classifies a spoken utterance as
conversation (DIRECT_RESPONSE), the reply comes from this fast local model so
first audio arrives in about a second. Utterances that ask for work keep the
owner loop and the operator's selected model, with tools.

Chosen 2026-11-14 on the M1 Max 32 GB: ``gemma4:latest`` (Gemma 4 E4B, 8B,
Q4_K_M; tools, vision, audio) with thinking off and an 8K window. Measured
prefill ~900 tok/s and decode ~51 tok/s. ``gemma4:12b`` prefilled at only
~210 tok/s (a 2.7K-token voice turn waited 14 s for its first token);
``qwen3:4b`` ignored ``think: false`` and rambled for 50 s.
Override with JAEGER_VOICE_MODEL=provider:model (e.g. ``ollama:gemma4:12b``).
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from datetime import datetime

DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "gemma4:latest"
VOICE_HISTORY = 8  # recent messages carried into a spoken turn
VOICE_CLIP = 400  # characters kept per history message
VOICE_BACKGROUND = 1200  # characters of recalled background kept before the request
VOICE_CTX = 8192
VOICE_STYLE = (
    "You are Jaeger, the user's personal AI assistant, talking with them by voice. "
    "Your reply is spoken aloud the moment you write it. "
    "Answer in one to three short, natural sentences. Lead with the answer. "
    "No markdown, lists, tables, emoji, code or URLs. Spell out symbols. "
    "If the person asks for real work (files, tools, research, messages), say briefly "
    "that you're on it; the work itself runs in the chat. "
    "The current local date and time are given with each request; use them. "
    "Never guess live facts you were not given (time in other places, weather, news, "
    "prices, scores, anything in files or accounts); say you'll check instead."
)

# Requests that need live facts or the user's data go to full Jaeger (tools), never
# to the small voice model, which would otherwise guess. Plain local time/date
# questions stay here: the model is handed the clock below.
_LIVE = re.compile(
    r"\b(?:"
    r"weather|forecast|temperature|rain(?:ing)?|snow(?:ing)?|humid|sunrise|sunset"
    r"|news|headlines?|stocks?|share price|price of|how much (?:is|does|are)|exchange rate|bitcoin|crypto"
    r"|scores?|who won|standings|game tonight|traffic|flights?|open now|hours (?:for|of)"
    r"|search|google|look (?:it |that )?up|find out|browse|website|web|online|latest|current(?:ly)?(?! (?:time|date|day))|recent|this week'?s"
    r"|files?|folders?|documents?|downloads|desktop|notes?|calendar|meetings?|schedule|emails?|inbox|messages?|texts?|slack"
    r"|reminders?|remind me|tasks?|to-?do|contacts?|photos?|screenshot|open (?:the |my )?\w+|run |install|repo|github|code"
    r"|time (?:is it )?(?:in|at)\s+\w|time zone in|what day is it in|in (?:tokyo|london|paris|new york|sydney|berlin|beijing|dubai|delhi|mumbai)\b"
    r")",
    re.IGNORECASE,
)


def needs_live_facts(request: str) -> bool:
    """True when a spoken request needs tools, live data or the user's files/accounts."""
    return bool(_LIVE.search(str(request or "")))


def _zone_name() -> str:
    name = os.environ.get("TZ", "").strip()
    if not name:
        try:
            real = os.path.realpath("/etc/localtime")
            name = real.split("zoneinfo/", 1)[1] if "zoneinfo/" in real else ""
        except OSError:
            name = ""
    return name


def clock_line(now: datetime | None = None) -> str:
    """The local date, time and zone, e.g. ``Sunday, November 15, 2026, 12:58 AM PST``."""
    now = (now or datetime.now()).astimezone()
    zone = _zone_name()
    hour = now.strftime("%I").lstrip("0") or "12"
    text = f"{now.strftime('%A, %B')} {now.day}, {now.year}, {hour}:{now.strftime('%M %p %Z')}"
    return f"{text} ({zone})" if zone else text


def selection() -> tuple[str, str]:
    raw = (os.environ.get("JAEGER_VOICE_MODEL") or "").strip()
    if raw and ":" in raw:
        provider, model = raw.split(":", 1)
        if provider and model:
            return provider.strip().lower(), model.strip()
    return DEFAULT_PROVIDER, DEFAULT_MODEL


def voice_brain() -> dict:
    provider, model = selection()
    return {
        "provider": provider,
        "model": model,
        "controls": {"ctx": VOICE_CTX, "reasoning_effort": "none", "max_tokens": 400},
        "system": VOICE_STYLE,
        "history": VOICE_HISTORY,
    }


def voice_history(rows) -> list:
    """Recent history for a spoken turn, shaped so Ollama can reuse its KV cache.

    The window start moves in steps of four messages (not one per turn), and each
    message is clipped deterministically, so consecutive voice turns share the
    same prompt prefix and only the new utterance is prefilled.
    """
    rows = list(rows or ())
    step = 4
    start = 0 if len(rows) <= VOICE_HISTORY else ((len(rows) - VOICE_HISTORY) // step + 1) * step
    out = []
    for row in rows[start:]:
        if isinstance(row, dict) and isinstance(row.get("content"), str) and len(row["content"]) > VOICE_CLIP:
            row = {**row, "content": row["content"][:VOICE_CLIP] + " …"}
        out.append(row)
    return out


def voice_prompt(prompt: str, request: str) -> str:
    """Keep the request intact and only a short slice of recalled background.

    Prefill is the main cost of a local first token (~900 tok/s on Gemma 4 E4B
    here, and its sliding-window cache is not reused between turns), so the up
    to 4,000 characters of recall used for typed turns are cut to a short lead.
    """
    prompt, request = str(prompt or ""), str(request or "").strip()
    # The clock rides at the end (not in the system prompt) so the cached prefix holds.
    return _voice_background(prompt, request) + f"\n\n[Local date and time now: {clock_line()}]"


def _voice_background(prompt: str, request: str) -> str:
    at = prompt.rfind(request) if request else -1
    if at <= 0:
        return prompt if len(prompt) <= VOICE_BACKGROUND + len(request) + 200 else request or prompt
    background, tail = prompt[:at], prompt[at:]
    if len(background) > VOICE_BACKGROUND:
        background = background[:VOICE_BACKGROUND].rstrip() + " …[background clipped for voice]\n\n"
    return background + tail


def warm(timeout: float = 30.0) -> None:
    """Load the local voice brain into memory (no output). Best effort, background."""
    provider, model = selection()
    if provider not in {"ollama", "ollama-local"}:
        return

    def run() -> None:
        try:
            from jaeger_ai.core.models.router import resolve_ollama_base_url
            base = (resolve_ollama_base_url(openai_compat=False) or "http://127.0.0.1:11434").rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
        except Exception:  # noqa: BLE001
            base = "http://127.0.0.1:11434"
        body = json.dumps({"model": model, "messages": [], "keep_alive": "30m",
                           "options": {"num_ctx": VOICE_CTX}}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(
                base + "/api/chat", body, {"Content-Type": "application/json"}), timeout=timeout).read()
        except Exception:  # noqa: BLE001 — warming is an optimisation only
            pass

    threading.Thread(target=run, name="voice-brain-warm", daemon=True).start()
