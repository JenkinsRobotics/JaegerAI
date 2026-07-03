"""Playbook skills — markdown skill definitions the agent reads on demand.

A skill is a folder under ``skills/`` with a ``SKILL.md``: YAML
frontmatter (name, description, tags) + a markdown body of instructions.
Skills are *dynamic* — some are pure playbooks, many carry embedded
shell/Python or a ``scripts/`` folder. The agent discovers them
(``skill`` tool: list / search) and reads one (view) to follow it,
running whatever it contains with its normal tools.

Separate from :mod:`skill_loader` — that imports Python *code* skills
that register tools. A playbook skill registers no tools; it is
knowledge + procedure the agent executes with `terminal` / `execute_code`.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# skills/ sits at the package root:  core/skills/ → core/ → jaeger_os/ → skills/
_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "agent" / "skills"


# Where a skill came from — for trust decisions and a future curator
# that must never prune a user-written skill (audit gap #8).
_VALID_ORIGINS = ("builtin", "user", "agent", "marketplace")


@dataclass
class PlaybookSkill:
    name: str
    category: str
    description: str
    path: Path                       # the SKILL.md file
    tags: list[str] = field(default_factory=list)
    # Provenance: "builtin" (shipped), "user" (hand-written), "agent"
    # (the agent authored it), "marketplace" (installed from elsewhere).
    origin: str = "builtin"
    # Discovery metadata (all optional). ``platforms`` empty = every OS;
    # otherwise a skill is hidden on a platform it does not list.
    # ``requires_tools`` HIDES the skill when its tools aren't registered;
    # ``requires_toolsets`` auto-loads the named toolsets on `skill view`.
    platforms: list[str] = field(default_factory=list)
    requires_tools: list[str] = field(default_factory=list)
    requires_toolsets: list[str] = field(default_factory=list)
    tier: str = "standard"  # routing hint: native | preferred | standard | fallback


def read_skill_origin(folder: Path) -> str:
    """A skill folder's provenance — from a ``.origin`` marker file if
    present, else ``builtin`` (the default for shipped skills)."""
    try:
        marker = (folder / ".origin").read_text(encoding="utf-8").strip()
        if marker in _VALID_ORIGINS:
            return marker
    except OSError:
        pass
    return "builtin"


def mark_skill_origin(folder: Path, origin: str) -> None:
    """Stamp a skill folder with its provenance — a ``.origin`` file.
    Called when a skill is authored (``agent``) or installed
    (``marketplace``). Unknown values are ignored."""
    if origin not in _VALID_ORIGINS:
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".origin").write_text(origin + "\n", encoding="utf-8")
    except OSError:
        pass


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse a leading ``---`` YAML frontmatter block. ``{}`` if absent."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        import yaml
        data = yaml.safe_load(text[3:end])
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _tags_of(fm: dict[str, Any]) -> list[str]:
    meta = fm.get("metadata")
    if isinstance(meta, dict):
        hermes = meta.get("hermes")
        if isinstance(hermes, dict) and isinstance(hermes.get("tags"), list):
            return [str(t) for t in hermes["tags"]]
    if isinstance(fm.get("tags"), list):
        return [str(t) for t in fm["tags"]]
    return []


def _str_list(fm: dict[str, Any], key: str) -> list[str]:
    """A frontmatter field coerced to a list of non-empty strings. Accepts a
    bare string (treated as a one-item list) or a list."""
    val = fm.get(key)
    if isinstance(val, str):
        val = [val]
    if not isinstance(val, list):
        return []
    return [str(v).strip() for v in val if str(v).strip()]


# Platform names — ``macos`` is first-class; common aliases normalise to it.
_PLATFORM_ALIASES = {
    "mac": "macos", "macos": "macos", "osx": "macos", "darwin": "macos",
    "linux": "linux",
    "win": "windows", "windows": "windows",
}


def _normalize_platforms(raw: list[str]) -> list[str]:
    """Map declared platform names onto canonical ``macos`` / ``linux`` /
    ``windows``, dropping anything unrecognised."""
    out: list[str] = []
    for name in raw:
        norm = _PLATFORM_ALIASES.get(name.strip().lower())
        if norm and norm not in out:
            out.append(norm)
    return out


def _current_platform() -> str:
    """This host as a canonical platform name."""
    plat = sys.platform
    if plat == "darwin":
        return "macos"
    if plat.startswith("win"):
        return "windows"
    return "linux"


def _platform_ok(skill: PlaybookSkill) -> bool:
    """True when ``skill`` runs on this host — a skill that declares no
    platforms runs everywhere."""
    return not skill.platforms or _current_platform() in skill.platforms


def _disabled_playbook_names() -> set[str]:
    """Playbook names disabled via ``skills.disabled_playbooks`` in the bound
    instance config. Empty when no instance is bound."""
    try:
        from jaeger_os.core.instance.schemas import Config, load_yaml
        from jaeger_os.core.context import get_layout

        cfg = load_yaml(get_layout().config_path, Config)
        return {str(n) for n in cfg.skills.disabled_playbooks}
    except Exception:  # noqa: BLE001 — no instance / no config is fine
        return set()


def _instance_skills_dir() -> Path | None:
    """The bound instance's ``skills/`` dir — where agent-authored
    playbooks live (the agent's writes are sandboxed to it). ``None``
    when no instance is bound, or when it is the bundled dir itself."""
    try:
        from jaeger_os.core.context import get_layout

        d = get_layout().skills_dir.resolve()
        return d if d != _SKILLS_DIR.resolve() else None
    except Exception:  # noqa: BLE001 — no instance bound is fine
        return None


# Discovery cache: stat-signature → parsed result. The signature is
# (path, mtime, size) for every SKILL.md — a stat-only scan, far cheaper
# than re-reading + re-parsing 89 files on each call (boot hits this several
# times). Any edit changes a stat, so the cache self-invalidates and
# hot-reload still works.
_DISCOVERY_CACHE: dict[str, Any] = {"sig": None, "result": None}


def _discovery_signature(roots: list[Path]) -> tuple:
    sig: list[tuple] = []
    for root in roots:
        if not root.is_dir():
            continue
        for md in sorted(root.rglob("SKILL.md")):
            try:
                st = md.stat()
                sig.append((str(md), st.st_mtime, st.st_size))
            except OSError:
                pass
    return tuple(sig)


def discover_playbooks() -> list[PlaybookSkill]:
    """Every playbook skill — from the bundled ``skills/`` tree **and**
    the bound instance's ``skills/`` — so a playbook the agent authored
    itself is found, not just shipped ones. On a name collision the
    instance copy wins, mirroring :mod:`skill_loader`.

    Cached on a stat signature: a second call with an unchanged skills tree
    skips the read+parse and returns the prior result."""
    roots: list[Path] = [_SKILLS_DIR]
    inst = _instance_skills_dir()
    if inst is not None:
        roots.append(inst)

    sig = _discovery_signature(roots)
    if _DISCOVERY_CACHE["sig"] == sig and _DISCOVERY_CACHE["result"] is not None:
        return _DISCOVERY_CACHE["result"]

    by_name: dict[str, PlaybookSkill] = {}
    for root in roots:                 # instance scanned last → it wins
        if not root.is_dir():
            continue
        for md in root.rglob("SKILL.md"):
            folder = md.parent
            # Presence-based unification: ANY folder with a SKILL.md is a recipe.
            # A folder that ALSO ships a module registers tools (skill_loader) —
            # so a skill can be both. No "code_skill vs playbook" split. See
            # dev/docs/skill_unification.md.
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            fm = _parse_frontmatter(text)
            if fm.get("archived"):
                continue  # retired skill — metadata flag, excluded from the surface
            try:
                rel = folder.relative_to(root)
                category = rel.parts[0] if len(rel.parts) > 1 else "general"
            except ValueError:
                category = "general"
            skill = PlaybookSkill(
                name=str(fm.get("name") or folder.name),
                category=category,
                description=str(fm.get("description") or "").strip(),
                path=md,
                tags=_tags_of(fm),
                origin=read_skill_origin(folder),
                platforms=_normalize_platforms(_str_list(fm, "platforms")),
                requires_tools=_str_list(fm, "requires_tools"),
                requires_toolsets=_str_list(fm, "requires_toolsets"),
                tier=str(fm.get("tier") or "standard").strip().lower(),
            )
            by_name[skill.name] = skill
    result = sorted(by_name.values(), key=lambda s: (s.category, s.name))
    _DISCOVERY_CACHE["sig"] = sig
    _DISCOVERY_CACHE["result"] = result
    return result


def _select_available(
    skills: list[PlaybookSkill], disabled: set[str],
    available_tools: set[str] | None = None,
) -> list[PlaybookSkill]:
    """Filter discovered skills to those the agent should see — drop those
    for another OS, those disabled in config, and (when ``available_tools``
    is given) those whose ``requires_tools`` aren't all present, so a skill
    that needs an absent tool doesn't clutter the index."""
    out = [s for s in skills if _platform_ok(s) and s.name not in disabled]
    if available_tools is not None:
        out = [s for s in out if all(t in available_tools
                                     for t in s.requires_tools)]
    return out


def available_playbooks(
    available_tools: set[str] | None = None,
) -> list[PlaybookSkill]:
    """Playbook skills the agent should actually see: every discovered skill
    minus those for another platform, those disabled in the instance config,
    and (when ``available_tools`` is given) those whose required tools are
    absent. The `skill` tool and the prompt index use this; the raw
    :func:`discover_playbooks` is kept for internal callers (e.g. curation)."""
    return _select_available(discover_playbooks(), _disabled_playbook_names(),
                             available_tools)


_SKILL_INDEX_MAX_CHARS = 1400
_SKILL_INDEX_TRUNCATE_SUFFIX = "\n…(more — use skill search)"


def _format_skill_index(skills: list[PlaybookSkill]) -> str:
    """Render a compact, prompt-ready index of ``skills`` — grouped by
    category, names only. Empty string for an empty list.

    The total output (body + truncation suffix) is hard-capped at
    :data:`_SKILL_INDEX_MAX_CHARS`. Earlier the cap was applied to
    the body alone, so the suffix pushed the actual prompt section
    above the budget; we reserve the suffix's length up front."""
    if not skills:
        return ""
    by_cat: dict[str, list[str]] = {}
    for s in skills:
        by_cat.setdefault(s.category, []).append(s.name)
    lines = [
        "Skill library — experienced playbooks for non-trivial tasks. Call "
        'skill(action="view", name="…") to follow one, or '
        'skill(action="search", query="…") to find one:',
    ]
    for cat in sorted(by_cat):
        lines.append(f"- {cat}: {', '.join(sorted(by_cat[cat]))}")
    text = "\n".join(lines)
    if len(text) > _SKILL_INDEX_MAX_CHARS:
        budget = _SKILL_INDEX_MAX_CHARS - len(_SKILL_INDEX_TRUNCATE_SUFFIX)
        text = text[:budget].rstrip() + _SKILL_INDEX_TRUNCATE_SUFFIX
    return text


def _short_function(desc: str) -> str:
    """A 3-8 word 'what it does' for the always-on skill menu — first
    clause of the SKILL.md description, trimmed."""
    fn = (desc or "").strip().replace("\n", " ")
    fn = fn.split(". ")[0].split(" — ")[0]
    return (fn[:57].rstrip() + "…") if len(fn) > 58 else fn


def build_skill_index(available_tools: set[str] | None = None) -> str:
    """A ONE-LINE skill pointer for the system prompt. The 87 playbook names
    now live as an ENUM on the ``use_skill`` tool (the model's native action
    space), so the old ~1.9k-token prose menu is gone — this just reminds the
    model the capability exists and which tool loads a skill. ``skill(list)``
    still gives the full enriched catalog on demand."""
    skills = available_playbooks(available_tools)
    if not skills:
        return ""
    return (
        f"Skills: you have {len(skills)} specialized playbooks (research, "
        "creative, codebase inspection, apps/services, macOS control, …), "
        "exposed as the name enum on the use_skill tool. For any specialized "
        'task, call use_skill(name="…") to load the recipe and follow it '
        "BEFORE reaching for raw tools. skill(action=\"list\") shows the full "
        "catalog with descriptions if you need to browse."
    )


def find_playbook(name: str) -> PlaybookSkill | None:
    """Resolve a playbook by exact then substring name match."""
    needle = (name or "").strip().lower()
    if not needle:
        return None
    skills = available_playbooks()
    for s in skills:
        if s.name.lower() == needle:
            return s
    for s in skills:
        if needle in s.name.lower():
            return s
    return None
