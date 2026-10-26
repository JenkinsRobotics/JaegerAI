"""Episode planning: brief + build logs -> outline, script and shot list.

Uses the instance's ``external_model`` (``base_url`` + ``model``) through the
OpenAI-compatible ``/chat/completions`` endpoint that Ollama serves, so the
default is whatever ``config.yaml`` names (``glm-5.3-flash:cloud`` today).
Only the URL and model name are read from the config; no credentials.

Channel-specific prompts (channel name, host description, privacy rules) are
loaded from ``youtube.toml`` in the instance directory — see
:mod:`.channel_config`.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .channel_config import ChannelConfig, load_channel_config

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "glm-5.3-flash:cloud"


@dataclass(frozen=True)
class ModelSettings:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL


def load_model_settings(config_path: Path | None = None) -> ModelSettings:
    """Read ``external_model.base_url`` / ``.model`` from the instance config.

    Falls back to the defaults when the file or keys are missing. Reads only
    those two keys.
    """
    path = config_path or Path.home() / ".jaeger" / "instances" / "jaeger" / "config.yaml"
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ImportError, ValueError):
        return ModelSettings()
    ext = data.get("external_model") or {}
    return ModelSettings(
        base_url=str(ext.get("base_url") or DEFAULT_BASE_URL),
        model=str(ext.get("model") or DEFAULT_MODEL),
    )


def build_messages(
    brief: str,
    build_logs: list[str],
    episode: str,
    channel_config: ChannelConfig | None = None,
) -> list[dict]:
    """Build chat messages for episode generation.

    If ``channel_config`` is not provided, loads it from the instance directory.
    """
    if channel_config is None:
        channel_config = load_channel_config()
    logs = "\n\n".join(f"### Build log {i}\n{text.strip()}"
                       for i, text in enumerate(build_logs, 1)) or "(none yet)"
    user = (f"Episode request: {episode.strip()}\n\n"
            f"## Project brief\n{brief.strip()}\n\n## Build logs\n{logs}\n")
    return [{"role": "system", "content": channel_config.build_system_prompt()},
            {"role": "user", "content": user}]


#: glm-5.3-flash is a reasoning model. With Ollama 0.33's default effort it
#: spent an 8000-token budget thinking and returned empty content (seen live
#: 2026-10-16); "none" leaked the thinking into content ending in </think>.
#: "low" returned clean content, so it is the default.
DEFAULT_REASONING_EFFORT = "low"


def chat(settings: ModelSettings, messages: list[dict], *,
         max_tokens: int = 8000, timeout: float = 600.0,
         reasoning_effort: str | None = DEFAULT_REASONING_EFFORT, opener=None) -> str:
    """One non-streaming chat completion; returns the reply text."""
    payload = {"model": settings.model, "messages": messages,
               "max_tokens": max_tokens, "temperature": 0.7, "stream": False}
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        settings.base_url.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with (opener or urllib.request.urlopen)(request, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    choice = (payload.get("choices") or [{}])[0]
    content = ((choice.get("message") or {}).get("content") or "").strip()
    if not content:
        reason = choice.get("finish_reason")
        raise RuntimeError(
            f"model {settings.model} returned no text (finish_reason={reason}); "
            "a reasoning model may have spent the budget — raise --max-tokens")
    return _strip_fences(_strip_thinking(content))


def _strip_thinking(text: str) -> str:
    """Drop leaked chain-of-thought: everything up to a closing </think>."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


def _strip_fences(text: str) -> str:
    match = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", text.strip(), re.S)
    return match.group(1).strip() if match else text


REQUIRED_SECTIONS = ("## Hook", "## Outline", "## Shot list", "## Narration")


def missing_sections(script_md: str) -> list[str]:
    return [s for s in REQUIRED_SECTIONS if s.lower() not in script_md.lower()]


def generate_script(brief_path: Path, out_path: Path, *, episode: str,
                    log_paths: list[Path] = (), settings: ModelSettings | None = None,
                    max_tokens: int = 8000,
                    reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
                    opener=None) -> Path:
    settings = settings or load_model_settings()
    brief = Path(brief_path).read_text(encoding="utf-8")
    logs = [Path(p).read_text(encoding="utf-8") for p in log_paths]
    text = chat(settings, build_messages(brief, logs, episode),
                max_tokens=max_tokens, reasoning_effort=reasoning_effort,
                opener=opener)
    gaps = missing_sections(text)
    header = (f"<!-- generated by `jaeger channel script` with {settings.model}; "
              f"DRAFT — needs operator approval -->\n")
    if gaps:
        header += f"<!-- WARNING: missing sections: {', '.join(gaps)} -->\n"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(header + text.strip() + "\n", encoding="utf-8")
    return out_path
