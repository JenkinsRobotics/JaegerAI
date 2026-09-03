"""PATH probe of known agent CLIs.

This is the onboarding catalog — not a second control plane. Each spec
names the binary, the non-interactive argv, and how the prompt is
passed. ``which_cli`` searches PATH plus the extra dirs OpenClaw-style
installs land in (``~/.grok/bin``, ``~/bin``, Homebrew).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


EXTRA_PATH_DIRS: tuple[str, ...] = (
    "~/.local/bin",
    "~/.grok/bin",
    "~/bin",
    "/opt/homebrew/bin",
)


@dataclass(frozen=True, slots=True)
class BackendSpec:
    """One known agent CLI that can serve as a Jaeger brain."""

    id: str
    executables: tuple[str, ...]
    args: tuple[str, ...]
    prompt_mode: str  # "stdin" | "placeholder"
    credential_env: tuple[str, ...] = ()
    catalog: bool = True
    display_name: str = ""
    probe_args: tuple[str, ...] = ("--version",)

    @property
    def provider_slug(self) -> str:
        return f"{self.id}-cli"


# Prompt is "{prompt}" in args when prompt_mode == "placeholder".
# stdin backends read the flattened prompt from stdin (no shell).
KNOWN_BACKENDS: tuple[BackendSpec, ...] = (
    BackendSpec(
        id="claude",
        executables=("claude",),
        args=("--print", "--output-format", "json", "--permission-mode", "dontAsk"),
        prompt_mode="stdin",
        credential_env=("ANTHROPIC_API_KEY",),
        display_name="Claude Code",
    ),
    BackendSpec(
        id="codex",
        executables=("codex",),
        args=(
            "exec", "--json", "--sandbox", "workspace-write",
            "--skip-git-repo-check", "-",
        ),
        prompt_mode="stdin",
        credential_env=("OPENAI_API_KEY",),
        display_name="Codex CLI",
    ),
    BackendSpec(
        id="grok",
        executables=("grok",),
        # Grok's documented one-shot today takes the prompt as an argv
        # value after --single. Stdin is not the published interface.
        args=(
            "--single", "{prompt}", "--output-format", "json",
            "--permission-mode", "dontAsk",
        ),
        prompt_mode="placeholder",
        credential_env=("XAI_API_KEY",),
        display_name="Grok CLI",
    ),
    BackendSpec(
        id="gemini",
        executables=("gemini",),
        args=("--prompt", "{prompt}"),
        prompt_mode="placeholder",
        credential_env=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        display_name="Gemini CLI",
    ),
    BackendSpec(
        id="hermes",
        executables=("hermes", "hermes-agent"),
        args=("chat", "-q", "{prompt}"),
        prompt_mode="placeholder",
        credential_env=(
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY", "NOUS_API_KEY",
        ),
        display_name="Hermes Agent",
    ),
    BackendSpec(
        id="ollama",
        executables=("ollama",),
        args=("run", "{prompt}"),
        prompt_mode="placeholder",
        credential_env=("OLLAMA_HOST",),
        # Already a Jaeger HTTP provider — list as an installed CLI, but
        # do not add a competing selectable brain row.
        catalog=False,
        display_name="Ollama CLI",
    ),
)


def extra_path_dirs() -> list[Path]:
    """Resolved extra dirs that actually exist on this machine."""
    out: list[Path] = []
    seen: set[str] = set()
    for raw in EXTRA_PATH_DIRS:
        path = Path(raw).expanduser()
        key = str(path)
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        out.append(path)
    return out


def which_cli(name: str) -> str | None:
    """PATH first, then extra install dirs (OpenClaw onboard)."""
    found = shutil.which(name)
    if found:
        return found
    extra = os.pathsep.join(str(p) for p in extra_path_dirs())
    if extra:
        return shutil.which(name, path=extra)
    return None


def resolve_backend(backend_id: str) -> BackendSpec | None:
    """Look up a known spec by id (``claude``) or catalog name (``cli:claude``)."""
    raw = (backend_id or "").strip().lower()
    if raw.startswith("cli:"):
        raw = raw.split(":", 1)[1]
    if raw.endswith("-cli"):
        raw = raw[: -len("-cli")]
    for spec in KNOWN_BACKENDS:
        if spec.id == raw:
            return spec
    return None


def probe_backend(spec: BackendSpec) -> str | None:
    """Return the resolved executable path, or ``None`` if missing."""
    for candidate in spec.executables:
        found = which_cli(candidate)
        if found:
            return found
    return None


def get_spec(backend_id: str) -> BackendSpec:
    spec = resolve_backend(backend_id)
    if spec is None:
        raise KeyError(f"unknown CLI backend {backend_id!r}")
    return spec
