"""Static and runtime-aware quality audit for the playbook skill catalog."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import playbook_skills as pb

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TRIGGER_RE = re.compile(r"\b(use|load|when|whenever|for)\b", re.I)
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _finding(severity: str, skill: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "skill": skill, "code": code, "message": message}


def audit_catalog(
    *, available_tools: set[str] | None = None, runtime_complete: bool = False,
) -> dict[str, Any]:
    """Audit every physical SKILL.md plus distribution/runtime contracts."""
    if available_tools is None:
        try:
            from jaeger_os.core.tools.tool_registry import get_tools
            available_tools = {tool.name for tool in get_tools()}
        except Exception:  # noqa: BLE001
            available_tools = set()
        # The live registry is intentionally scoped to the current turn. An
        # audit must compare against the complete production catalog or it
        # falsely reports every lazy toolset/plugin tool as missing.
        try:
            from jaeger_agent.schemas.tool_bundles import JAEGER_TOOLSETS

            for definition in JAEGER_TOOLSETS.values():
                available_tools.update(definition.get("tools", ()))
        except Exception:  # noqa: BLE001
            pass

    findings: list[dict[str, str]] = []
    skills = pb.discover_playbooks()
    names = {skill.name for skill in skills}
    aliases: dict[str, str] = {}
    for skill in skills:
        for alias in skill.aliases:
            if alias in names or alias in aliases:
                findings.append(_finding(
                    "error", skill.name, "alias-collision",
                    f"alias {alias!r} collides with a skill or another alias",
                ))
            aliases[alias] = skill.name

        text = skill.path.read_text(encoding="utf-8", errors="replace")
        lines = len(text.splitlines())
        if not _NAME_RE.fullmatch(skill.name):
            findings.append(_finding(
                "error", skill.name, "invalid-name",
                "name is not portable lowercase kebab-case",
            ))
        if skill.name != skill.path.parent.name:
            findings.append(_finding(
                "warning", skill.name, "folder-mismatch",
                f"name does not match folder {skill.path.parent.name!r}",
            ))
        if not skill.description:
            findings.append(_finding("error", skill.name, "missing-description", "description is empty"))
        elif not _TRIGGER_RE.search(skill.description):
            findings.append(_finding(
                "warning", skill.name, "weak-trigger",
                "description says what but not clearly when to load the skill",
            ))
        if lines > 500 and skill.skill_class == "first-class":
            findings.append(_finding(
                "error", skill.name, "oversized-first-class",
                f"first-class entrypoint has {lines} lines; migrate bulk to references",
            ))
        elif lines > 250 and skill.skill_class == "first-class":
            findings.append(_finding(
                "warning", skill.name, "large-first-class",
                f"first-class entrypoint has {lines} lines and needs review",
            ))
        elif lines > 130 and skill.skill_class == "first-class":
            findings.append(_finding(
                "warning", skill.name, "size-warning",
                f"first-class entrypoint has {lines} lines; target is 50-130",
            ))

        for raw in _LINK_RE.findall(text):
            target = raw.split("#", 1)[0].strip().strip("<>")
            if not target or re.match(r"^[a-z][a-z0-9+.-]*://", target, re.I):
                continue
            # Ignore Markdown-like examples containing assignment syntax.
            if "=" in target or " " in target:
                continue
            if not (
                "/" in target
                or target.endswith((".md", ".json", ".yaml", ".yml", ".py", ".sh"))
            ):
                continue
            if not (skill.path.parent / target).exists():
                findings.append(_finding(
                    "error", skill.name, "broken-reference",
                    f"linked file does not exist: {target}",
                ))

        missing = sorted(set(skill.requires_tools) - available_tools)
        if missing:
            severity = (
                "error"
                if runtime_complete and skill.lifecycle == "core"
                else "warning"
            )
            findings.append(_finding(
                severity, skill.name, "missing-required-tools",
                f"required tools are not registered: {missing}",
            ))
        if skill.lifecycle == "plugin" and not skill.requires_plugins:
            findings.append(_finding(
                "error", skill.name, "missing-plugin-contract",
                "plugin lifecycle skill does not declare requires-plugins",
            ))
        try:
            from jaeger_ai.core.safety.skills_guard import scan_skill
            scan = scan_skill(skill.path.parent, name=skill.name)
            if scan.is_danger:
                findings.append(_finding(
                    "error" if skill.lifecycle == "core" else "warning",
                    skill.name, "security-danger",
                    f"skill safety scan returned DANGER with {len(scan.findings)} finding(s)",
                ))
        except Exception:  # noqa: BLE001
            pass

    counts = {level: sum(f["severity"] == level for f in findings)
              for level in ("error", "warning", "info")}
    lifecycle_counts: dict[str, int] = {}
    for skill in skills:
        lifecycle_counts[skill.lifecycle] = lifecycle_counts.get(skill.lifecycle, 0) + 1
    return {
        "ok": counts["error"] == 0,
        "skill_count": len(skills),
        "active_count": len(pb.available_playbooks()),
        "knowledge_pack_count": sum(s.skill_class == "knowledge-pack" for s in skills),
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
        "counts": counts,
        "findings": findings,
    }


__all__ = ["audit_catalog"]
