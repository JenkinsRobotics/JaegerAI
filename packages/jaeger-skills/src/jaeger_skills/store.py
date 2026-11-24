"""Standalone skill validation, frontmatter parsing, and relevance ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_SKILL_BYTES = 64_000
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


class SkillValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SkillSummary:
    name: str
    description: str
    path: str = ""


def clean_skill_name(name: str) -> str:
    n = (name or "").strip().lower().replace(" ", "-")
    if not _NAME_RE.match(n) or ".." in n:
        raise SkillValidationError("Skill name must be 2-64 chars: a-z, 0-9, '.', '_' or '-'")
    return n


def parse_frontmatter(text: str) -> dict[str, str]:
    if not (text or "").startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def validate_skill_markdown(name: str, content: str) -> str:
    clean = clean_skill_name(name)
    text = (content or "").replace("\r\n", "\n")
    if not text.strip():
        raise SkillValidationError("Skill content is empty")
    if len(text.encode("utf-8")) > MAX_SKILL_BYTES:
        raise SkillValidationError(f"Skill content exceeds {MAX_SKILL_BYTES} bytes")
    fm = parse_frontmatter(text)
    if not fm.get("name") or not fm.get("description"):
        raise SkillValidationError("SKILL.md needs YAML frontmatter with 'name' and 'description'")
    if clean_skill_name(fm["name"]) != clean:
        raise SkillValidationError(f"Frontmatter name {fm['name']!r} must match the skill name {clean!r}")
    return text if text.endswith("\n") else text + "\n"


def rank_skills(query: str, skills: list[SkillSummary], *, limit: int = 5) -> list[SkillSummary]:
    """Fast deterministic token-overlap ranker for progressive skill loading."""
    q_tokens = set(_TOKEN_RE.findall((query or "").lower()))
    if not q_tokens:
        return skills[:limit]
    scored: list[tuple[float, SkillSummary]] = []
    for sk in skills:
        name_tokens = set(_TOKEN_RE.findall(sk.name.lower()))
        desc_tokens = set(_TOKEN_RE.findall(sk.description.lower()))
        score = 3.0 * len(q_tokens & name_tokens) + 1.0 * len(q_tokens & desc_tokens)
        if score > 0:
            scored.append((score, sk))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [sk for _, sk in scored[: max(1, limit)]]
