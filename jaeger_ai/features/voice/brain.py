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
import threading
import urllib.request

DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "gemma4:latest"
VOICE_HISTORY = 12  # recent messages carried into a spoken turn
VOICE_CTX = 8192
VOICE_STYLE = (
    "You are Jaeger, the user's personal AI assistant, talking with them by voice. "
    "Your reply is spoken aloud the moment you write it. "
    "Answer in one to three short, natural sentences. Lead with the answer. "
    "No markdown, lists, tables, emoji, code or URLs. Spell out symbols. "
    "If the person asks for real work (files, tools, research, messages), say briefly "
    "that you're on it; the work itself runs in the chat."
)


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

    The window start moves in steps of six messages (not one per turn), and each
    message is clipped deterministically, so consecutive voice turns share the
    same prompt prefix and only the new utterance is prefilled.
    """
    rows = list(rows or ())
    step = 6
    start = 0 if len(rows) <= VOICE_HISTORY else ((len(rows) - VOICE_HISTORY) // step + 1) * step
    out = []
    for row in rows[start:]:
        if isinstance(row, dict) and isinstance(row.get("content"), str) and len(row["content"]) > 600:
            row = {**row, "content": row["content"][:600] + " …"}
        out.append(row)
    return out


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
