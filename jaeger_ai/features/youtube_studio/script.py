"""Episode planning: brief + build logs -> outline, script and shot list.

Uses the instance's ``external_model`` (``base_url`` + ``model``) through the
OpenAI-compatible ``/chat/completions`` endpoint that Ollama serves, so the
default is whatever ``config.yaml`` names (``glm-5.3-flash:cloud`` today).
Only the URL and model name are read from the config; no credentials.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "glm-5.3-flash:cloud"

#: The channel's ground rules. The brief can contain personal background;
#: the show is a build show, so the prompt keeps that off screen.
SYSTEM_PROMPT = """\
You write episodes for the YouTube channel "Matthew Walks the Way", a build show
about Project Hab-1 (a habitat-in-a-box living and robotics workshop built on a
small budget with local AI, 3D printing and CNC).

On-screen cast:
- HOST: an AI version of Matthew. It presents, explains and narrates.
- ROBOT: the Jenkins Robotics robot co-host. Short, dry, practical lines.
The real Matthew only appears as hands and build footage. This is NOT a show
about his personal life: never mention his age, family, parents, relationships,
marriage, finances beyond the project budget, or where he lives beyond "the
garage workshop". Never invent costs, measurements or test results: if a
number is not in the brief or build logs, write [TBD].

Return markdown with exactly these sections, in this order:
# <Episode title>
## Hook (0:00-0:30)
## Outline
(numbered beats with rough timestamps)
## Shot list
(markdown table: | # | Shot | Source | Notes | where Source is one of
BUILD FOOTAGE, AI HOST, ROBOT, SCREEN, B-ROLL)
## Narration
(one spoken line per paragraph, each starting with "HOST:" or "ROBOT:")
## Open questions for Matthew
"""


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


def build_messages(brief: str, build_logs: list[str], episode: str) -> list[dict]:
    logs = "\n\n".join(f"### Build log {i}\n{text.strip()}"
                       for i, text in enumerate(build_logs, 1)) or "(none yet)"
    user = (f"Episode request: {episode.strip()}\n\n"
            f"## Project brief\n{brief.strip()}\n\n## Build logs\n{logs}\n")
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def chat(settings: ModelSettings, messages: list[dict], *,
         max_tokens: int = 8000, timeout: float = 600.0, opener=None) -> str:
    """One non-streaming chat completion; returns the reply text."""
    body = json.dumps({"model": settings.model, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0.7,
                       "stream": False}).encode()
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
    return _strip_fences(content)


def _strip_fences(text: str) -> str:
    match = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", text.strip(), re.S)
    return match.group(1).strip() if match else text


REQUIRED_SECTIONS = ("## Hook", "## Outline", "## Shot list", "## Narration")


def missing_sections(script_md: str) -> list[str]:
    return [s for s in REQUIRED_SECTIONS if s.lower() not in script_md.lower()]


def generate_script(brief_path: Path, out_path: Path, *, episode: str,
                    log_paths: list[Path] = (), settings: ModelSettings | None = None,
                    max_tokens: int = 8000, opener=None) -> Path:
    settings = settings or load_model_settings()
    brief = Path(brief_path).read_text(encoding="utf-8")
    logs = [Path(p).read_text(encoding="utf-8") for p in log_paths]
    text = chat(settings, build_messages(brief, logs, episode),
                max_tokens=max_tokens, opener=opener)
    gaps = missing_sections(text)
    header = (f"<!-- generated by `jaeger channel script` with {settings.model}; "
              f"DRAFT — needs Matthew's approval -->\n")
    if gaps:
        header += f"<!-- WARNING: missing sections: {', '.join(gaps)} -->\n"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(header + text.strip() + "\n", encoding="utf-8")
    return out_path
