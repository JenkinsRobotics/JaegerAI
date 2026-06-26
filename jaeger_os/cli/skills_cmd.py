"""``jaeger skills`` — view the skill tree.

Subcommands:
  jaeger skills              — overview by category
  jaeger skills view <id>    — detail on one skill
  jaeger skills tree         — full text-rendered tree
"""

from __future__ import annotations

import argparse
from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "skills",
        help="view + inspect the agent's skill tree",
        description=(
            "Inspect the XP-driven skill tree for the active instance. "
            "The tree is the same data the eventual GUI radial view "
            "reads — terminal first by design."
        ),
    )
    parser.set_defaults(_handler=run_overview)
    sub = parser.add_subparsers(dest="skills_subcommand")
    sub.required = False

    overview = sub.add_parser(
        "overview",
        help="one-line-per-skill grouped by category (default)",
    )
    overview.set_defaults(_handler=run_overview)

    tree = sub.add_parser(
        "tree",
        help="full prereq tree (text-rendered)",
    )
    tree.set_defaults(_handler=run_tree)

    view = sub.add_parser(
        "view",
        help="detail on one skill (XP, status, unlocks)",
    )
    view.add_argument("skill_id", help="e.g. animation.image")
    view.set_defaults(_handler=run_view)

    notes = sub.add_parser(
        "notes",
        help="recipe-skill usage notes (the self-improvement journal)",
    )
    notes.add_argument("skill", nargs="?", default="",
                       help="a skill name, or blank for the per-skill tally")
    notes.set_defaults(_handler=run_notes)


# ── status formatting ─────────────────────────────────────────────

_STATUS_GLYPH = {
    "mastered": "★",
    "active":   "●",
    "available":"○",
    "locked":   "·",
}

_STATUS_COLOUR = {
    "mastered": c.yellow,
    "active":   c.green,
    "available":c.cyan,
    "locked":   c.grey,
}


def _status_badge(status: str) -> str:
    glyph = _STATUS_GLYPH.get(status, "?")
    colour = _STATUS_COLOUR.get(status, c.dim)
    return colour(f"{glyph} {status}")


def _load_registry() -> Any | None:
    """Build a registry from the operator's instance state + seed
    catalog, returning ``None`` if no instance is set up."""
    from jaeger_os.skill_tree import SkillTreeRegistry, seed_default_tree

    layout = c.get_active_instance_layout()
    if layout is None:
        return None
    reg = SkillTreeRegistry.for_instance(layout)
    seed_default_tree(reg)
    return reg


# ── overview ──────────────────────────────────────────────────────

def run_overview(args: Any) -> int:
    reg = _load_registry()
    if reg is None:
        print(c.red("no active instance — run the setup wizard first"))
        return 1
    skills = list(reg.all())
    print(f"\n{c.bold('Skill tree')} "
          f"({c.dim(str(len(skills)) + ' skills total')})\n")
    # Group by category, sorted by status (mastered first), then by id.
    categories: dict[str, list] = {}
    for s in skills:
        categories.setdefault(s.category or "uncategorised", []).append(s)
    _order = ("animation", "voice", "vision", "motor", "light", "core")
    cats_sorted = sorted(
        categories.keys(),
        key=lambda k: (_order.index(k) if k in _order else 99, k),
    )
    for cat in cats_sorted:
        nodes = sorted(
            categories[cat],
            key=lambda n: (
                {"mastered": 0, "active": 1, "available": 2,
                 "locked": 3}.get(n.status, 4),
                n.id,
            ),
        )
        mastered = sum(1 for n in nodes if n.status == "mastered")
        total = len(nodes)
        header = (
            f"{c.bold(cat.upper())}  "
            f"{c.dim(f'{mastered}/{total} mastered')}"
        )
        print(header)
        for n in nodes:
            line = (
                f"  {_status_badge(n.status):<22}  "
                f"{c.bold(n.id):<26}  "
                f"L{n.level}  "
                f"XP {n.xp:>4}/{n.xp_to_mastery}"
            )
            print(line)
        print()
    return 0


# ── tree ──────────────────────────────────────────────────────────

def run_tree(args: Any) -> int:
    reg = _load_registry()
    if reg is None:
        print(c.red("no active instance — run the setup wizard first"))
        return 1
    skills = {s.id: s for s in reg.all()}
    # Find roots (no prereqs).
    roots = [s for s in skills.values() if not s.prerequisites]
    print(f"\n{c.bold('Skill tree (prereq graph)')}\n")
    visited: set[str] = set()
    for root in sorted(roots, key=lambda r: r.id):
        _render_subtree(root.id, skills, "", visited)
    print()
    return 0


def _render_subtree(node_id: str, skills: dict, prefix: str,
                    visited: set[str]) -> None:
    node = skills.get(node_id)
    if node is None:
        return
    badge = _status_badge(node.status)
    line = f"{prefix}{c.bold(node.id)}  {badge}  L{node.level}"
    if node_id in visited:
        line += c.dim(" (already shown)")
        print(line)
        return
    visited.add(node_id)
    print(line)
    children = sorted(
        (cid for cid in node.unlocks if cid in skills),
    )
    if not children:
        return
    for i, child_id in enumerate(children):
        is_last = i == len(children) - 1
        branch = "└─ " if is_last else "├─ "
        next_prefix = prefix + ("   " if is_last else "│  ")
        _render_subtree(child_id, skills,
                         prefix + branch, visited)
        # The above renders the child's id on a single line; chase
        # its unlocks at next_prefix indent.
        grand_children_node = skills.get(child_id)
        if grand_children_node and grand_children_node.unlocks:
            for j, gid in enumerate(
                sorted(g for g in grand_children_node.unlocks
                       if g in skills)
            ):
                gis_last = j == len(grand_children_node.unlocks) - 1
                gb = "└─ " if gis_last else "├─ "
                _render_subtree(
                    gid, skills,
                    next_prefix + gb, visited,
                )


# ── view ──────────────────────────────────────────────────────────

def run_view(args: Any) -> int:
    reg = _load_registry()
    if reg is None:
        print(c.red("no active instance — run the setup wizard first"))
        return 1
    node = reg.get(args.skill_id)
    if node is None:
        print(c.red(f"no such skill: {args.skill_id!r}"))
        return 1
    print()
    print(f"  {c.bold(node.id)}  {_status_badge(node.status)}")
    print(f"  {c.dim(node.description or '(no description)')}")
    print()
    print(c.kv("Category",  c.cyan(node.category)))
    print(c.kv("Level",     f"L{node.level} / max L{node.max_level}"))
    print(c.kv("XP",        f"{node.xp} / {node.xp_to_mastery}"))
    print(c.kv("Progress",  c.bar(node.xp / max(1, node.xp_to_mastery))))
    if node.xp_to_next_level is not None:
        print(c.kv("Next-level threshold",
                   str(node.xp_to_next_level * node.level)))
    if node.prerequisites:
        print()
        print(f"  {c.bold('Prerequisites')}")
        for pid in node.prerequisites:
            prereq = reg.get(pid)
            if prereq is None:
                print(f"    - {pid}  {c.red('(unknown)')}")
            else:
                print(f"    - {pid}  {_status_badge(prereq.status)}")
    if node.unlocks:
        print()
        print(f"  {c.bold('Unlocks when mastered')}")
        for cid in node.unlocks:
            child = reg.get(cid)
            if child is None:
                print(f"    - {cid}  {c.dim('(unknown)')}")
            else:
                print(f"    - {cid}  {_status_badge(child.status)}")
    print()
    return 0


# ── notes (recipe-skill self-improvement journal) ─────────────────

_OUTCOME_COLOUR = {"smooth": c.green, "slow": c.yellow, "issues": c.yellow,
                   "failed": c.red, "reviewing": c.cyan}


def run_notes(args: Any) -> int:
    layout = c.get_active_instance_layout()
    if layout is None:
        print(c.red("no active instance — run the setup wizard first"))
        return 1
    from jaeger_os.core import skill_notes
    skill = (getattr(args, "skill", "") or "").strip()
    if skill:
        notes = skill_notes.notes_for(layout, skill)
        if not notes:
            print(c.dim(f"no usage notes for {skill!r} yet"))
            return 0
        print(f"\n{c.bold(skill)} {c.dim(f'· {len(notes)} note(s)')}\n")
        for n in notes[-30:]:
            col = _OUTCOME_COLOUR.get(n.outcome, c.dim)
            print(f"  {col(f'{n.outcome:<9}')} {c.dim(n.ts)}  {n.note}")
        print()
        return 0
    summary = skill_notes.summary(layout)
    if not summary:
        print(c.dim("no skill-usage notes yet — the agent journals them as it works"))
        return 0
    print(f"\n{c.bold('Skill usage notes')}  {c.dim('(per-skill outcomes)')}\n")
    for sk, tally in sorted(summary.items(),
                            key=lambda kv: -(kv[1].get("failed", 0)
                                             + kv[1].get("issues", 0))):
        bad = tally.get("failed", 0) + tally.get("issues", 0)
        flag = c.red("  ← needs review") if bad >= 3 else ""
        parts = "  ".join(f"{o}:{tally[o]}" for o in
                          ("smooth", "slow", "issues", "failed") if tally.get(o))
        print(f"  {c.bold(sk):<24} {parts}{flag}")
    print()
    return 0
