"""Bundled production sandbox and tiered policy profiles.

Contains verbatim profiles from:
- OpenAI Codex (`codex_sbpl/*.sbpl`, Apache-2.0)
- Google Gemini CLI (`gemini_sb/*.sb`, `gemini_toml/*.toml`, Apache-2.0)
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

PROFILES_DIR = Path(__file__).resolve().parent
CODEX_SBPL_DIR = PROFILES_DIR / "codex_sbpl"
GEMINI_SB_DIR = PROFILES_DIR / "gemini_sb"
GEMINI_TOML_DIR = PROFILES_DIR / "gemini_toml"


def list_seatbelt_profiles() -> dict[str, list[str]]:
    return {
        "codex": sorted(p.name for p in CODEX_SBPL_DIR.glob("*.sbpl")),
        "gemini": sorted(p.name for p in GEMINI_SB_DIR.glob("*.sb")),
    }


def load_codex_sbpl(name: str) -> str:
    target = CODEX_SBPL_DIR / name
    if not target.is_file():
        raise FileNotFoundError(f"Unknown Codex SBPL profile: {name}")
    return target.read_text(encoding="utf-8")


def load_gemini_sb(name: str) -> str:
    target = GEMINI_SB_DIR / name
    if not target.is_file():
        raise FileNotFoundError(f"Unknown Gemini Seatbelt profile: {name}")
    return target.read_text(encoding="utf-8")


def load_gemini_policy_rules() -> dict[str, dict[str, Any]]:
    """Load all bundled Gemini CLI tiered TOML policy files."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(GEMINI_TOML_DIR.glob("*.toml")):
        out[path.stem] = tomllib.loads(path.read_text(encoding="utf-8"))
    return out


__all__ = [
    "CODEX_SBPL_DIR",
    "GEMINI_SB_DIR",
    "GEMINI_TOML_DIR",
    "list_seatbelt_profiles",
    "load_codex_sbpl",
    "load_gemini_policy_rules",
    "load_gemini_sb",
]
