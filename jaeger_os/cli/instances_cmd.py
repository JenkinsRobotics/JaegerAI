"""``jaeger instances`` — list / show the active / switch instances.

Operator-facing: every operation the GUI's "Instances" tab will do
goes through here first.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "instances",
        help="list / switch JROS instances",
        description=(
            "Enumerate the operator's local instances + show which "
            "one is active.  ``jaeger instances switch <name>`` "
            "rewrites the active-instance pointer; subsequent "
            "``./launch`` boots that instance."
        ),
    )
    parser.set_defaults(_handler=run_list)
    sub = parser.add_subparsers(dest="instances_subcommand")
    sub.required = False

    listp = sub.add_parser("list", help="list all known instances (default)")
    listp.set_defaults(_handler=run_list)

    show = sub.add_parser(
        "show", help="show the currently-active instance",
    )
    show.set_defaults(_handler=run_show)

    sw = sub.add_parser(
        "switch", help="set the active instance",
    )
    sw.add_argument("name", help="instance name to make active")
    sw.set_defaults(_handler=run_switch)


# ── list ──────────────────────────────────────────────────────────

def run_list(args: Any) -> int:
    instances = c.list_known_instances()
    active = c.get_active_instance_layout()
    active_root = active.root.resolve() if active is not None else None
    if not instances:
        print(c.red("no instances found"))
        print(c.dim(
            "Run ./launch and the setup wizard will create one."
        ))
        return 1
    print()
    print(f"  {c.bold('Known instances')}")
    print()
    for root in instances:
        name = root.name
        is_active = active_root is not None and root.resolve() == active_root
        marker = c.green("●") if is_active else c.dim("○")
        location = c.dim(str(root.resolve()))
        suffix = c.yellow(" (active)") if is_active else ""
        print(f"    {marker}  {c.bold(name):<24}  {location}{suffix}")
    print()
    return 0


# ── show ──────────────────────────────────────────────────────────

def run_show(args: Any) -> int:
    layout = c.get_active_instance_layout()
    if layout is None:
        print(c.red("no active instance set"))
        return 1
    print()
    print(f"  {c.bold('Active instance')}: {c.cyan(layout.root.name)}")
    print(f"  {c.dim(str(layout.root.resolve()))}")
    print()
    _print_instance_summary(layout)
    return 0


def _print_instance_summary(layout) -> None:
    """One-screen summary of the instance — identity + persona + skills."""
    # Identity
    try:
        from jaeger_os.core.instance.schemas import Identity, load_yaml
        ident = load_yaml(layout.identity_path, Identity)
        print(c.kv("Name", c.bold(ident.name)))
        if ident.role:
            print(c.kv("Role", ident.role))
        if ident.voice_id:
            print(c.kv("Voice", ident.voice_id))
    except Exception:  # noqa: BLE001
        print(c.kv("Identity", c.red("(unreadable)")))

    # Personality (optional)
    pj = layout.root / "personality.json"
    if pj.exists():
        try:
            from jaeger_os.personality import load_personality
            p = load_personality(pj)
            print()
            print(c.kv("Persona", c.bold(p.name or "(unnamed)")))
            print(c.kv("  Directness",
                       f"{c.bar(p.expression.directness)} {p.expression.directness:.2f}"))
            print(c.kv("  Warmth",
                       f"{c.bar(p.expression.warmth)} {p.expression.warmth:.2f}"))
            print(c.kv("  Sarcasm",
                       f"{c.bar(p.expression.sarcasm)} {p.expression.sarcasm:.2f}"))
            print(c.kv("  Humour",
                       f"{c.bar(p.expression.humor)} {p.expression.humor:.2f}"))
        except Exception:  # noqa: BLE001
            print(c.kv("Persona", c.red("(unreadable)")))
    else:
        print()
        print(c.kv("Persona",
                   c.dim("(no personality.json — defaults active)")))

    # Skill tree summary
    try:
        from jaeger_os.skill_tree import (
            SkillTreeRegistry, seed_default_tree,
        )
        reg = SkillTreeRegistry.for_instance(layout)
        seed_default_tree(reg)
        skills = list(reg.all())
        by_status: dict[str, int] = {}
        for s in skills:
            by_status[s.status] = by_status.get(s.status, 0) + 1
        print()
        print(c.kv("Skills",
                   f"{by_status.get('mastered', 0)} ★  "
                   f"{by_status.get('active', 0)} ●  "
                   f"{by_status.get('available', 0)} ○  "
                   f"{by_status.get('locked', 0)} ·"))
    except Exception:  # noqa: BLE001
        pass
    print()


# ── switch ────────────────────────────────────────────────────────

def run_switch(args: Any) -> int:
    """Switch the active instance by writing to the standard
    pointer file.  Implementation detail: the
    :func:`default_instance_name` resolver reads JAEGER_INSTANCE_NAME
    env var, then a ``~/.jaeger_os/active_instance`` file, then
    falls back to ``default``.

    We write the file so the change persists; env var takes
    precedence at boot if also set."""
    target = args.name.strip()
    if not target:
        print(c.red("instance name cannot be empty"))
        return 1

    instances = {p.name: p for p in c.list_known_instances()}
    if target not in instances:
        print(c.red(f"no instance named {target!r}"))
        known = ", ".join(sorted(instances.keys())) or "(none)"
        print(c.dim(f"known: {known}"))
        return 1

    # Write the pointer file alongside the standard instance root.
    pointer = Path.home() / ".jaeger_os" / "active_instance"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(target + "\n")
    print(c.green(f"switched to {target!r}"))
    print(c.dim(f"pointer: {pointer}"))
    return 0
