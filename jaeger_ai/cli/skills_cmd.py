"""``jaeger skills`` — the real skill catalog, history and rollback.

Subcommands:
  jaeger skills                      — catalog grouped by category
  jaeger skills search <text>        — filter by name/description
  jaeger skills view <name>          — one skill's SKILL.md and metadata
  jaeger skills history <name>       — saved versions of a skill Jaeger wrote
  jaeger skills rollback <name> <v>  — restore an earlier version
  jaeger skills revisions [name]     — self-improvement log
  jaeger skills notes [name]         — usage journal
  jaeger skills score [name]         — win-rates + retire candidates
"""

from __future__ import annotations

from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "skills",
        help="list, inspect, and roll back the agent's skills",
        description="The skills Jaeger can use (builtin playbooks, tool skills, and the ones it wrote itself).",
    )
    parser.set_defaults(_handler=run_overview)
    sub = parser.add_subparsers(dest="skills_subcommand")
    sub.required = False

    overview = sub.add_parser("list", help="catalog grouped by category (default)")
    overview.add_argument("--mine", action="store_true", help="only skills Jaeger or you wrote")
    overview.set_defaults(_handler=run_overview)

    search = sub.add_parser("search", help="filter skills by name or description")
    search.add_argument("query")
    search.set_defaults(_handler=run_search)

    view = sub.add_parser("view", help="show one skill")
    view.add_argument("name")
    view.set_defaults(_handler=run_view)

    history = sub.add_parser("history", help="saved versions of a skill")
    history.add_argument("name")
    history.set_defaults(_handler=run_history)

    rollback = sub.add_parser("rollback", help="restore an earlier version of a skill")
    rollback.add_argument("name")
    rollback.add_argument("version", help="e.g. v2")
    rollback.set_defaults(_handler=run_rollback)

    notes = sub.add_parser(
        "notes",
        help="recipe-skill usage notes (the self-improvement journal)",
    )
    notes.add_argument("skill", nargs="?", default="",
                       help="a skill name, or blank for the per-skill tally")
    notes.set_defaults(_handler=run_notes)

    revisions = sub.add_parser(
        "revisions",
        help="how skills changed over time (the self-improvement log)",
    )
    revisions.add_argument("skill", nargs="?", default="",
                           help="a skill name, or blank for per-skill revision counts")
    revisions.set_defaults(_handler=run_revisions)

    score = sub.add_parser(
        "score",
        help="recipe-skill win-rates + retire candidates (self-improvement)",
    )
    score.add_argument("skill", nargs="?", default="",
                       help="a skill name, or blank for all scored skills")
    score.set_defaults(_handler=run_score)


def _layout_or_fail() -> Any | None:
    layout = c.get_active_instance_layout()
    if layout is None:
        print(c.red("no active instance — run the setup wizard first"))
    return layout


def _catalog(layout: Any) -> list[dict[str, Any]]:
    from jaeger_ai.core.skills import service
    return list(service.list_skills(layout)["skills"])


def _origin_tag(row: dict[str, Any]) -> str:
    origin = row.get("origin") or "builtin"
    if origin == "agent":
        return c.green(" [by Jaeger]")
    if origin in ("user", "instance", "marketplace"):
        return c.cyan(f" [{origin}]")
    return ""


def _print_rows(rows: list[dict[str, Any]], title: str) -> None:
    from jaeger_agent.skill_improvement import skill_revisions
    layout = c.get_active_instance_layout()
    revs = skill_revisions.counts(layout) if layout is not None else {}
    print(f"\n{c.bold(title)} {c.dim(f'({len(rows)} skills)')}\n")
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_cat.setdefault(r.get("category") or "general", []).append(r)
    for cat in sorted(by_cat):
        items = by_cat[cat]
        print(f"  {c.bold(cat)} {c.dim(str(len(items)))}")
        for r in sorted(items, key=lambda x: x["name"].lower()):
            desc = (r.get("description") or "").replace("\n", " ")
            if len(desc) > 80:
                desc = desc[:77] + "…"
            off = c.grey(" (off)") if r.get("disabled") else ""
            rev = c.dim(f" · rev {revs[r['name']]}") if revs.get(r["name"]) else ""
            print(f"    {r['name']}{_origin_tag(r)}{off}{rev}  {c.dim(desc)}")
        print()


# ── list / search ─────────────────────────────────────────────────

def run_overview(args: Any) -> int:
    layout = _layout_or_fail()
    if layout is None:
        return 1
    rows = _catalog(layout)
    if getattr(args, "mine", False):
        rows = [r for r in rows if r.get("zone") == "instance"]
    _print_rows(rows, "Skills")
    print(c.dim("  jaeger skills view <name> · history <name> · rollback <name> <vN>\n"))
    return 0


def run_search(args: Any) -> int:
    layout = _layout_or_fail()
    if layout is None:
        return 1
    q = (args.query or "").strip().lower()
    rows = [r for r in _catalog(layout)
            if q in r["name"].lower() or q in (r.get("description") or "").lower()]
    _print_rows(rows, f"Skills matching {q!r}")
    return 0


# ── view ──────────────────────────────────────────────────────────

def run_view(args: Any) -> int:
    layout = _layout_or_fail()
    if layout is None:
        return 1
    name = (args.name or "").strip()
    row = next((r for r in _catalog(layout) if r["name"].lower() == name.lower()), None)
    if row is None:
        print(c.red(f"no skill named {name!r} — try `jaeger skills search {name}`"))
        return 1
    print(f"\n{c.bold(row['name'])}{_origin_tag(row)}  {c.dim(row.get('category') or '')}")
    print(f"  {row.get('description') or ''}")
    print(c.dim(f"  kinds: {', '.join(row.get('kinds') or [])} · {'editable' if row.get('mutable') else 'builtin (read-only)'}"
                f"{' · disabled' if row.get('disabled') else ''}"))
    if "playbook" in (row.get("kinds") or []):
        try:
            from jaeger_ai.core.skills import service
            detail = service.get_skill(layout, row["name"])
            body = str(detail.get("content") or "")
            if body:
                print()
                print(body if len(body) < 6000 else body[:6000] + c.dim("\n… (truncated)"))
        except Exception as exc:  # noqa: BLE001
            print(c.dim(f"  (content unavailable: {exc})"))
    print()
    return 0


# ── history / rollback ────────────────────────────────────────────

def run_history(args: Any) -> int:
    layout = _layout_or_fail()
    if layout is None:
        return 1
    from jaeger_agent.skill_improvement import skill_history as sh
    try:
        rows = sh.versions(layout, args.name)
    except sh.SkillHistoryError as exc:
        print(c.red(str(exc)))
        return 1
    if not rows:
        print(c.dim(f"{args.name!r} has no saved versions (only skills Jaeger edits through skill_manage are versioned)"))
        return 0
    print(f"\n{c.bold(args.name)} {c.dim(f'· {len(rows)} version(s)')}\n")
    for r in rows:
        print(f"  {c.bold(r['version']):<6} {c.dim(r['ts'] or 'original')}  {c.dim(r['origin'])}  {r['summary']}")
    print()
    return 0


def run_rollback(args: Any) -> int:
    layout = _layout_or_fail()
    if layout is None:
        return 1
    from jaeger_agent.skill_improvement import skill_history as sh
    try:
        out = sh.rollback(layout, args.name, args.version, origin="manual")
    except sh.SkillHistoryError as exc:
        print(c.red(str(exc)))
        return 1
    if out.get("changed"):
        print(c.green(f"{out['skill']} restored from {args.version} (saved as {out['version']})"))
    else:
        print(c.dim(f"{out['skill']} already matches {args.version}"))
    return 0


# ── notes (recipe-skill self-improvement journal) ─────────────────

_OUTCOME_COLOUR = {"smooth": c.green, "slow": c.yellow, "issues": c.yellow,
                   "failed": c.red, "reviewing": c.cyan}


def run_notes(args: Any) -> int:
    layout = c.get_active_instance_layout()
    if layout is None:
        print(c.red("no active instance — run the setup wizard first"))
        return 1
    from jaeger_agent.skill_improvement import skill_notes
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
    from jaeger_agent.skill_improvement import skill_revisions
    revs = skill_revisions.counts(layout)
    print(f"\n{c.bold('Skill usage notes')}  {c.dim('(per-skill outcomes)')}\n")
    for sk, tally in sorted(summary.items(),
                            key=lambda kv: -(kv[1].get("failed", 0)
                                             + kv[1].get("issues", 0))):
        bad = tally.get("failed", 0) + tally.get("issues", 0)
        flag = c.red("  ← needs review") if bad >= 3 else ""
        rev = c.dim(f"  · rev {revs[sk]}") if revs.get(sk) else ""
        parts = "  ".join(f"{o}:{tally[o]}" for o in
                          ("smooth", "slow", "issues", "failed") if tally.get(o))
        print(f"  {c.bold(sk):<24} {parts}{rev}{flag}")
    print()
    return 0


# ── revisions (the self-improvement audit trail) ──────────────────

def run_revisions(args: Any) -> int:
    layout = c.get_active_instance_layout()
    if layout is None:
        print(c.red("no active instance — run the setup wizard first"))
        return 1
    from jaeger_agent.skill_improvement import skill_revisions
    skill = (getattr(args, "skill", "") or "").strip()
    if skill:
        revs = skill_revisions.revisions_for(layout, skill)
        if not revs:
            print(c.dim(f"{skill!r} has no recorded revisions"))
            return 0
        print(f"\n{c.bold(skill)} {c.dim(f'· {len(revs)} revision(s)')}\n")
        for r in revs:
            delta = c.green(f"  {r.delta}") if r.delta else ""
            print(f"  {c.bold(r.version or '?'):<5} {c.dim(r.ts)}  "
                  f"{c.dim(r.origin)}{delta}")
            if r.summary:
                print(f"        {r.summary}")
        print()
        return 0
    counts = skill_revisions.counts(layout)
    if not counts:
        print(c.dim("no skill revisions yet — recorded as the agent improves skills"))
        return 0
    print(f"\n{c.bold('Skill revisions')}  {c.dim('(times each skill was improved)')}\n")
    for sk, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        latest = skill_revisions.latest(layout, sk)
        tail = c.dim(f"  → {latest.version}") if latest and latest.version else ""
        print(f"  {c.bold(sk):<24} {n} revision(s){tail}")
    print()
    return 0


# ── score (win-rate + retirement candidates) ──────────────────────

def run_score(args: Any) -> int:
    layout = c.get_active_instance_layout()
    if layout is None:
        print(c.red("no active instance — run the setup wizard first"))
        return 1
    from jaeger_agent.skill_improvement import skill_maintenance as sm
    from jaeger_agent.skill_improvement import skill_notes
    skill = (getattr(args, "skill", "") or "").strip()
    skills = [skill] if skill else sorted(skill_notes.summary(layout))
    if not skills:
        print(c.dim("no skill-usage notes yet — scores accrue as the agent works"))
        return 0
    candidates = set(sm.retire_candidates(layout))
    print(f"\n{c.bold('Skill scores')}  {c.dim('(win-rate from post-use notes)')}\n")
    for sk in skills:
        s = sm.skill_score(layout, sk)
        rate = f"{s['win_rate'] * 100:.0f}%"
        flag = c.red("  ← retire candidate") if sk in candidates else ""
        print(f"  {c.bold(sk):<24} {s['wins']}/{s['uses']} wins  "
              f"{c.dim(rate)}{flag}")
    print()
    return 0
