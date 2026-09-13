"""Bundled OS 1 utility intelligence.

The operator's agent model is a choice.  This model is part of OS 1: it is
small enough to ship with the native application and is available before an
instance, Ollama, provider credentials, or a network connection exists.

The utility model never owns configuration writes.  Callers give it verified
facts and use it for language: setup guidance, diagnostics, recovery help,
and intent extraction.  Deterministic Python services remain responsible for
detecting hardware, validating selections, and mutating state.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

SYSTEM_MODEL_KEY = "qwen3-1.7b-system-q4_k_m"
SYSTEM_MODEL_ENV = "JAEGER_SYSTEM_MODEL"

_FALLBACK_GUIDANCE = {
    "welcome": (
        "Welcome to OS 1. I am the system setup guide. I can explain each "
        "decision while OS 1 detects a recommended configuration for this Mac."
    ),
    "architecture": (
        "OS 1 keeps the operating environment separate from your agent. "
        "The agent can change models and character without losing its identity."
    ),
    "character": (
        "Choose how your agent should relate to you. This changes its working "
        "style and personality; every field can be adjusted later."
    ),
    "calibration": (
        "These preferences shape how directly your agent communicates. "
        "Choose the closest starting point; the agent can adapt over time."
    ),
    "identity": (
        "Give the agent a name and a practical role. The optional directive "
        "is a durable instruction for how it should approach your work."
    ),
    "model": (
        "OS 1 has inspected the models and providers available on this Mac. "
        "You can accept the recommendation or open the manual controls."
    ),
    "permissions": (
        "Choose how much autonomy the agent should have. Confirmation mode "
        "asks before consequential actions and is the recommended starting point."
    ),
    "review": (
        "Review the detected configuration. OS 1 will save it, start the exact "
        "model shown here, and verify a real response before continuing."
    ),
    "first_contact": (
        "The selected model is responding. I will complete calibration, then "
        "transfer the conversation to your agent in its chosen voice."
    ),
}


def system_model_path(*, auto_download: bool = False) -> Path:
    """Resolve the bundled utility GGUF without silently using another model."""
    explicit = os.environ.get(SYSTEM_MODEL_ENV, "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Bundled OS utility model is missing: {path}")
        return path

    from jaeger_ai.core.models.model_resolver import resolve_model_path

    return Path(resolve_model_path(
        SYSTEM_MODEL_KEY,
        auto_download=auto_download,
        progress=auto_download,
    ))


def _plain(text: str) -> str:
    """Remove Qwen thinking wrappers and formatting from spoken guidance."""
    body = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.I)
    body = re.sub(r"[*_`#]+", "", body)
    return " ".join(body.split()).strip()


class SystemUtilityModel:
    """Lazy, reusable Qwen context for OS-owned conversation."""

    def __init__(self, model_path: Path | None = None) -> None:
        self._path = model_path
        self._client: Any = None
        self._lock = threading.RLock()
        self.error: str | None = None

    @property
    def loaded(self) -> bool:
        return self._client is not None

    @property
    def path(self) -> Path:
        return self._path or system_model_path(auto_download=False)

    def load(self) -> None:
        with self._lock:
            if self._client is not None:
                return
            try:
                from jaeger_ai.core.models.llm_client import LlamaCppPythonClient

                self._client = LlamaCppPythonClient(
                    model_path=self.path,
                    ctx=4096,
                    batch=256,
                    ubatch=256,
                    warmup=True,
                )
                self.error = None
            except Exception as exc:
                self.error = str(exc)
                raise

    def unload(self) -> None:
        with self._lock:
            client, self._client = self._client, None
            if client is not None:
                unload = getattr(client, "unload", None)
                if callable(unload):
                    unload()

    def respond(self, message: str, *, mode: str = "offline_help", facts: str = "") -> str:
        """Answer from verified facts without giving the model mutation authority."""
        with self._lock:
            self.load()
            system = (
                "You are the technical setup and recovery guide built into OS 1. "
                "OS 1 is the operating environment, not an AI name. Be calm, concise, "
                "and precise. Explain technical choices in ordinary language. Use only "
                "the verified facts supplied by the host. Never claim you changed a "
                "setting or detected hardware. Never role-play as the user's agent. "
                f"Current mode: {mode}."
            )
            prompt = (
                f"Verified host facts:\n{facts or 'No additional facts supplied.'}\n\n"
                f"Request:\n{message}\n\n/no_think"
            )
            result = self._client.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=180,
                temperature=0.2,
                top_p=0.8,
                stream=False,
            )
            text = _plain(str(getattr(result, "text", "") or ""))
            if not text:
                raise ValueError("OS utility model returned an empty response")
            return text

    def onboarding_guide(self, step: str, facts: dict[str, Any] | None = None) -> str:
        """Produce the short technical narration for one onboarding stage."""
        normalized = (step or "welcome").strip().lower()
        fallback = _FALLBACK_GUIDANCE.get(normalized, _FALLBACK_GUIDANCE["welcome"])
        fact_lines = [
            f"{key}: {value}" for key, value in sorted((facts or {}).items())
        ]
        try:
            return self.respond(
                "Explain the current onboarding stage in two short spoken sentences. "
                f"Stage: {normalized}. Required meaning: {fallback}",
                mode="onboarding",
                facts="\n".join(fact_lines),
            )
        except Exception:
            return fallback

    def status(self) -> dict[str, Any]:
        try:
            path = self.path
        except Exception as exc:
            return {
                "model": SYSTEM_MODEL_KEY,
                "available": False,
                "loaded": False,
                "error": str(exc),
            }
        return {
            "model": SYSTEM_MODEL_KEY,
            "available": path.is_file(),
            "loaded": self.loaded,
            "path": str(path),
            "error": self.error,
            "roles": ["onboarding", "diagnostics", "recovery", "offline_help"],
        }


__all__ = [
    "SYSTEM_MODEL_ENV",
    "SYSTEM_MODEL_KEY",
    "SystemUtilityModel",
    "system_model_path",
]
