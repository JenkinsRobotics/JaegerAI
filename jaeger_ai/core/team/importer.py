"""Team importer: bot definitions -> Jaeger ``character/v1`` agent packs.

Input is a folder with one sub-folder per bot::

    <src>/<bot>/bot.yaml        name, description, persona (or instructions),
                                avatar (relative image path), skills (names, optional)
    <src>/<bot>/avatar.png      optional
    <src>/<bot>/skills/<skill>/SKILL.md   optional; ``--skills DIR`` adds a shared folder

The source is untrusted (the OpenMausBot package-import rule): only the fields
above are read, every privilege-bearing field (tool grants, role) is set here,
and nothing else crosses over. It copies NO memory, NO secrets and NO connector
credentials: such keys are dropped and reported, such files are never opened for
copying, and a skill file whose text looks like a credential is skipped.

Dry run is the default. ``--apply`` writes the packs under the operator state
root (never the repository) and registers each pack as a team specialist in the
AgentRegistry, so it runs through the existing Gateway turn path (own session,
notes namespace, skill scope, tool allowlist, hooks and approvals).

    python -m jaeger_ai.core.team.importer SRC [--skills DIR] [--team pilot] [--apply]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Tools every imported agent gets. Read/plan/notes/skills plus handing work to a
#: teammate. Anything that writes or reaches outside goes through approvals anyway,
#: and the owner widens grants on the agent's Setup, never through an import.
DEFAULT_TEAM_TOOLS: tuple[str, ...] = (
    "call_agent", "get_agent_result", "agent_notes", "read_file", "search_files",
    "web_search", "web_extract", "update_plan", "get_time", "use_skill", "skill",
)
ALLOWED_KEYS = frozenset({"name", "display_name", "title", "description", "persona", "instructions",
                          "role", "avatar", "avatar_seed", "skills", "slug"})
_SECRET_KEY = re.compile(r"(?i)(memory|memories|secret|token|password|passwd|credential|api[_-]?key|"
                         r"oauth|connector|connection|cookie|session|private[_-]?key|vault|login)")
_SECRET_FILE = re.compile(r"(?i)(^\.env|\.pem$|\.key$|\.p12$|\.sqlite3?$|\.db$|credential|token|secret|"
                          r"password|cookie|memory|memories|vault|keychain|id_rsa|id_ed25519)")
_SECRET_TEXT = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|xox[abpr]-[A-Za-z0-9-]{10,}|"
    r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|AIza[0-9A-Za-z_-]{30,})")
SKILL_FILE_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".py", ".sh", ".mjs", ".js", ".ts", ".csv"})
MAX_SKILL_FILE = 256 * 1024
AVATAR_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"})
MAX_AVATAR = 2 * 1024 * 1024


@dataclass
class PackPlan:
    slug: str
    display_name: str
    description: str
    persona: str
    avatar: Path | None
    avatar_seed: str
    skills: dict[str, Path] = field(default_factory=dict)       # skill name -> source dir
    skill_files: dict[str, list[Path]] = field(default_factory=dict)
    dropped_keys: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    source: str = ""

    def manifest(self, team: str, tools: tuple[str, ...]) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "schema": "character/v1",
            "character": self.slug,
            "name": self.display_name,
            "version": 1,
            "author": "team-import",
            "license": "owner",
            "description": self.description,
            "kind": "agent",
            "identity": {"role": self.description},
            "prompt": {"custom_instructions": self.persona},
            "team": {
                "team": team,
                "display_name": self.display_name,
                "avatar_seed": self.avatar_seed,
                "skills": sorted(self.skills),
                "allowed_tools": list(tools),
                "imported_from": self.source,
            },
        }
        if self.avatar is not None:
            doc["card"] = f"avatar{self.avatar.suffix.lower()}"
            doc["assets"] = {"avatar": {"file": doc["card"]}}
        return doc


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:56]
    return slug or "agent"


def _read_definition(folder: Path) -> dict[str, Any]:
    for name in ("bot.yaml", "bot.yml", "bot.json", "agent.yaml", "agent.json"):
        path = folder / name
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
            if not isinstance(data, dict):
                raise ValueError(f"{path}: bot definition must be a mapping")
            return data
    raise FileNotFoundError(f"{folder}: no bot.yaml / bot.json")


def _frontmatter_name(skill_md: Path) -> str | None:
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return None
    name = meta.get("name") if isinstance(meta, dict) else None
    return str(name).strip() if name else None


def _skill_dirs(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if not root.is_dir():
        return out
    for md in sorted(root.rglob("SKILL.md")):
        if any(_SECRET_FILE.search(part) for part in md.relative_to(root).parts[:-1]):
            continue
        name = _frontmatter_name(md) or md.parent.name
        out.setdefault(name, md.parent)
    return out


def _safe_skill_files(skill_dir: Path, skipped: list[str]) -> list[Path]:
    files: list[Path] = []
    for path in sorted(skill_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(skill_dir)
        label = f"{skill_dir.name}/{rel}"
        if any(_SECRET_FILE.search(part) for part in rel.parts) or any(p.startswith(".") for p in rel.parts):
            skipped.append(f"{label} (secret/memory-like name)")
            continue
        if path.suffix.lower() not in SKILL_FILE_SUFFIXES:
            skipped.append(f"{label} (file type not copied)")
            continue
        if path.stat().st_size > MAX_SKILL_FILE:
            skipped.append(f"{label} (over {MAX_SKILL_FILE // 1024} KB)")
            continue
        if _SECRET_TEXT.search(path.read_text(encoding="utf-8", errors="replace")):
            skipped.append(f"{label} (looks like it contains a credential)")
            continue
        files.append(path)
    return files


def plan_bot(folder: Path, shared_skills: dict[str, Path]) -> PackPlan:
    raw = _read_definition(folder)
    dropped = sorted(k for k in raw if k not in ALLOWED_KEYS or _SECRET_KEY.search(str(k)))
    data = {k: v for k, v in raw.items() if k in ALLOWED_KEYS and not _SECRET_KEY.search(str(k))}
    name = str(data.get("display_name") or data.get("name") or folder.name).strip()
    if not name:
        raise ValueError(f"{folder}: bot has no name")
    description = str(data.get("description") or data.get("title") or data.get("role") or "").strip()
    persona = str(data.get("persona") or data.get("instructions") or description).strip()
    slug = slugify(str(data.get("slug") or name))
    plan = PackPlan(slug=slug, display_name=name, description=description, persona=persona, avatar=None,
                    avatar_seed=str(data.get("avatar_seed") or hashlib.sha256(slug.encode()).hexdigest()[:12]),
                    dropped_keys=dropped, source=folder.name)
    avatar = data.get("avatar")
    if isinstance(avatar, str) and avatar.strip():
        candidate = (folder / avatar).resolve()
        if (candidate.is_file() and candidate.is_relative_to(folder.resolve())
                and candidate.suffix.lower() in AVATAR_SUFFIXES and candidate.stat().st_size <= MAX_AVATAR):
            plan.avatar = candidate
        else:
            plan.skipped_files.append(f"avatar {avatar!r} (missing, outside the bot folder, or not an image)")
    available = {**shared_skills, **_skill_dirs(folder / "skills")}
    wanted = data.get("skills")
    names = [str(s) for s in wanted] if isinstance(wanted, list) else sorted(_skill_dirs(folder / "skills"))
    for skill in names:
        src = available.get(skill)
        if src is None:
            plan.skipped_files.append(f"skill {skill!r} (not found in the supplied skills folders)")
            continue
        files = _safe_skill_files(src, plan.skipped_files)
        if not any(f.name == "SKILL.md" for f in files):
            plan.skipped_files.append(f"skill {skill!r} (SKILL.md not copyable)")
            continue
        plan.skills[skill] = src
        plan.skill_files[skill] = files
    return plan


def plan_folder(src: Path, skills_dir: Path | None = None) -> list[PackPlan]:
    shared = _skill_dirs(skills_dir) if skills_dir else {}
    plans: list[PackPlan] = []
    seen: set[str] = set()
    for folder in sorted(p for p in src.iterdir() if p.is_dir() and not p.name.startswith(".")):
        try:
            plan = plan_bot(folder, shared)
        except FileNotFoundError:
            continue
        if plan.slug in seen:
            raise ValueError(f"two bots map to the same id {plan.slug!r}")
        seen.add(plan.slug)
        plans.append(plan)
    return plans


def write_pack(plan: PackPlan, dest: Path, *, team: str, tools: tuple[str, ...] = DEFAULT_TEAM_TOOLS) -> Path:
    pack = dest / plan.slug
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "character.yaml").write_text(yaml.safe_dump(plan.manifest(team, tools), sort_keys=False, allow_unicode=True),
                                         encoding="utf-8")
    if plan.avatar is not None:
        shutil.copyfile(plan.avatar, pack / f"avatar{plan.avatar.suffix.lower()}")
    for skill, files in plan.skill_files.items():
        root = plan.skills[skill]
        for path in files:
            target = pack / "skills" / slugify(skill) / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    return pack


def default_packs_root() -> Path:
    from jaeger_ai.core.instance.instance import operator_state_root
    return operator_state_root() / "team" / "packs"


def default_skills_root() -> Path:
    from jaeger_ai.core.instance.instance import resolve_instance_dir
    return resolve_instance_dir() / "skills" / "team"


def register_pack(plan: PackPlan, pack: Path, *, team: str, registry: Any = None,
                  skills_root: Path | None = None, tools: tuple[str, ...] = DEFAULT_TEAM_TOOLS) -> Any:
    """Install the pack's skills where specialist skill scope finds them and register the agent."""
    from jaeger_ai.core.agent_registry import AgentRegistry
    from jaeger_ai.core.agent_registry.types import AgentKind, AgentRole

    registry = registry or AgentRegistry()
    if plan.skills:
        root = (skills_root or default_skills_root()) / plan.slug
        shutil.copytree(pack / "skills", root, dirs_exist_ok=True)
    meta = {
        "framework": "jaeger", "product_shape": "grok_bot", "specialist": True, "team": team,
        "specialty": plan.description or plan.display_name, "summary": plan.description,
        "operator_instructions": plan.persona, "skills": sorted(plan.skills), "allowed_tools": list(tools),
        "avatar_seed": plan.avatar_seed, "pack_path": str(pack), "character_schema": "character/v1",
        "avatar_file": f"avatar{plan.avatar.suffix.lower()}" if plan.avatar else None,
        "imported_from": plan.source, "replace": True,
    }
    return registry.create_agent(plan.slug, kind=AgentKind.NATIVE, role=AgentRole.SPECIALIST,
                                 display_name=plan.display_name, metadata=meta, make_active=False,
                                 scaffold_instance=True)


def report(plans: list[PackPlan], *, apply: bool, dest: Path) -> dict[str, Any]:
    return {
        "mode": "apply" if apply else "dry-run",
        "dest": str(dest),
        "copied": {"memory": False, "secrets": False, "connector_credentials": False},
        "agents": [{
            "id": f"native:{p.slug}", "display_name": p.display_name, "description": p.description,
            "skills": sorted(p.skills), "avatar": bool(p.avatar), "dropped_keys": p.dropped_keys,
            "skipped": p.skipped_files,
        } for p in plans],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jaeger-team-import", description=__doc__.split("\n\n")[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("--skills", type=Path, default=None, help="shared skills folder (each skill a SKILL.md dir)")
    ap.add_argument("--team", default="pilot")
    ap.add_argument("--dest", type=Path, default=None, help="pack output folder (default: <state>/team/packs)")
    ap.add_argument("--apply", action="store_true", help="write packs and register agents (default: dry run)")
    args = ap.parse_args(argv)
    if not args.src.is_dir():
        print(f"not a folder: {args.src}", file=sys.stderr)
        return 2
    plans = plan_folder(args.src, args.skills)
    dest = args.dest or (default_packs_root() if args.apply else Path("<state>/team/packs"))
    if args.apply:
        for plan in plans:
            pack = write_pack(plan, dest, team=args.team)
            register_pack(plan, pack, team=args.team)
    print(json.dumps(report(plans, apply=args.apply, dest=dest), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
