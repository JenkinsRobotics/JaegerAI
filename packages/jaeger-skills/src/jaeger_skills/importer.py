"""External Agent Importer (Claude Code, Codex, Cursor, OpenClaw -> JaegerAI).

Adapted from Hermes Agent's MIT-licensed ``import-agent`` workflow:
- Discovers local agent homes (``~/.claude``, ``~/.codex``, ``~/.cursor``, ``~/.openclaw``).
- Supports ``dry_run=True`` preview before copying anything.
- Imports persona/memory markdown (``SOUL.md``, ``MEMORY.md``, ``USER.md``) into
  ``<state_dir>/imported/<source>/`` and scans every imported ``SKILL.md`` through
  ``jaeger_skills.scan_skill`` (fail-closed against malicious or secret-leaking skills).
- Never reads or migrates API keys or secrets automatically.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .skills_guard import scan_skill, should_allow_install
from .store import clean_skill_name

KNOWN_AGENT_SOURCES: dict[str, tuple[str, ...]] = {
    "claude-code": (".claude",),
    "codex": (".codex",),
    "cursor": (".cursor",),
    "openclaw": (".openclaw",),
}

_DOC_FILENAMES: tuple[str, ...] = ("SOUL.md", "MEMORY.md", "USER.md", "CLAUDE.md", "AGENTS.md")


@dataclass
class ImportPlanItem:
    kind: str  # "doc" | "skill"
    name: str
    source_path: str
    target_path: str
    allowed: bool = True
    reason: str = ""
    imported: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentImportReport:
    source: str
    source_root: str
    dry_run: bool
    found: bool
    items: list[ImportPlanItem] = field(default_factory=list)
    imported_count: int = 0
    blocked_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "source": self.source,
            "source_root": self.source_root,
            "dry_run": self.dry_run,
            "found": self.found,
            "imported_count": self.imported_count,
            "blocked_count": self.blocked_count,
            "items": [i.to_dict() for i in self.items],
        }


def discover_external_agents(*, home_dir: Path | None = None) -> list[dict[str, Any]]:
    """Detect installed external coding/assistant agent directories under ``home_dir``."""
    base = Path(home_dir).expanduser().resolve() if home_dir is not None else Path.home().resolve()
    found: list[dict[str, Any]] = []
    for source, rels in KNOWN_AGENT_SOURCES.items():
        for rel in rels:
            cand = base / rel
            if cand.is_dir():
                skill_count = sum(1 for _ in cand.glob("skills/*/SKILL.md"))
                doc_names = [fn for fn in _DOC_FILENAMES if (cand / fn).is_file()]
                found.append({
                    "source": source,
                    "path": str(cand),
                    "docs": doc_names,
                    "skill_count": skill_count,
                })
                break
    return found


def import_external_agent(
    source: str,
    *,
    target_state_dir: Path,
    source_dir: Path | None = None,
    home_dir: Path | None = None,
    dry_run: bool = True,
    max_skills: int = 50,
) -> AgentImportReport:
    """Preview or import docs and security-scanned skills from an external agent into JaegerAI."""
    src_key = (source or "").strip().lower()
    if src_key not in KNOWN_AGENT_SOURCES and source_dir is None:
        raise ValueError(f"unsupported source {source!r}; expected one of {sorted(KNOWN_AGENT_SOURCES)}")

    if source_dir is not None:
        root = Path(source_dir).expanduser().resolve()
    else:
        base = Path(home_dir).expanduser().resolve() if home_dir is not None else Path.home().resolve()
        root = (base / KNOWN_AGENT_SOURCES[src_key][0]).resolve()

    if not root.is_dir():
        return AgentImportReport(
            source=src_key,
            source_root=str(root),
            dry_run=dry_run,
            found=False,
        )

    dest_state = Path(target_state_dir).expanduser().resolve()
    docs_dest = dest_state / "imported" / src_key
    skills_dest = dest_state / "skills" / f"imported-{src_key}"
    items: list[ImportPlanItem] = []
    imported_count = 0
    blocked_count = 0

    # 1. Persona / memory markdown docs (never .env / credentials / json tokens)
    for fn in _DOC_FILENAMES:
        src_file = root / fn
        if not src_file.is_file() or src_file.is_symlink():
            continue
        dst_file = docs_dest / fn
        item = ImportPlanItem(
            kind="doc",
            name=fn,
            source_path=str(src_file),
            target_path=str(dst_file),
            allowed=True,
            reason="markdown_doc",
        )
        if not dry_run:
            docs_dest.mkdir(parents=True, exist_ok=True)
            dst_file.write_text(src_file.read_text(encoding="utf-8", errors="replace")[:200_000], encoding="utf-8")
            item.imported = True
            imported_count += 1
        items.append(item)

    # 2. Skills (each scanned through jaeger_skills.scan_skill — fail-closed!)
    skill_roots = [root / "skills"]
    seen_skills: set[str] = set()
    for sroot in skill_roots:
        if not sroot.is_dir():
            continue
        for skill_md in sorted(sroot.glob("*/SKILL.md"))[: max(1, int(max_skills))]:
            if skill_md.is_symlink():
                continue
            skill_folder = skill_md.parent
            safe_name = clean_skill_name(skill_folder.name)
            if not safe_name or safe_name in seen_skills:
                continue
            seen_skills.add(safe_name)
            scan = scan_skill(skill_folder, source=f"import:{src_key}")
            allowed, reason = should_allow_install(scan)
            dst_md = skills_dest / safe_name / "SKILL.md"
            item = ImportPlanItem(
                kind="skill",
                name=safe_name,
                source_path=str(skill_md),
                target_path=str(dst_md),
                allowed=allowed,
                reason=reason or scan.verdict,
            )
            if not allowed:
                blocked_count += 1
            elif not dry_run:
                dst_md.parent.mkdir(parents=True, exist_ok=True)
                dst_md.write_text(skill_md.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                item.imported = True
                imported_count += 1
            items.append(item)

    return AgentImportReport(
        source=src_key,
        source_root=str(root),
        dry_run=dry_run,
        found=True,
        items=items,
        imported_count=imported_count,
        blocked_count=blocked_count,
    )


__all__ = [
    "AgentImportReport",
    "ImportPlanItem",
    "KNOWN_AGENT_SOURCES",
    "discover_external_agents",
    "import_external_agent",
]
