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
            "Enumerate the operator's local instances + show which one "
            "is active. ``jaeger instances set-default <name>`` rewrites "
            "the active-instance pointer; a bare ``jaeger`` then runs it."
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

    create = sub.add_parser("create", help="create a new instance (wizard)")
    create.add_argument("name", nargs="?", help="instance name (optional)")
    create.set_defaults(_handler=run_create)

    edit = sub.add_parser(
        "edit", help="reconfigure an existing instance (re-run the wizard)")
    edit.add_argument("name", help="instance name to edit")
    edit.set_defaults(_handler=run_edit)

    delete = sub.add_parser("delete", help="delete an instance")
    delete.add_argument("name", help="instance name to delete")
    delete.add_argument("--yes", action="store_true",
                        help="skip the type-to-confirm prompt")
    delete.set_defaults(_handler=run_delete)

    sd = sub.add_parser(
        "set-default", help="set the agent a bare `jaeger` runs")
    sd.add_argument("name", help="instance name to make the default")
    sd.set_defaults(_handler=run_set_default)

    # ``switch`` kept as a back-compat alias of ``set-default``.
    sw = sub.add_parser("switch", help="alias of set-default")
    sw.add_argument("name", help="instance name to make active")
    sw.set_defaults(_handler=run_set_default)


# ── list ──────────────────────────────────────────────────────────

def run_list(args: Any) -> int:
    instances = c.list_known_instances()
    active = c.get_active_instance_layout()
    active_root = active.root.resolve() if active is not None else None
    if not instances:
        print(c.red("no instances found"))
        print(c.dim("Run `jaeger setup [name]` to create one."))
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


# ── set-default (a.k.a. switch) ────────────────────────────────────

def run_set_default(args: Any) -> int:
    """Set the sticky-default instance a bare ``jaeger`` runs.

    Writes the canonical ``<install_root>/.jaeger_os/active_instance``
    pointer AND rewrites the sourceable ``jaeger.env`` pin — the wizard
    leaves ``JAEGER_INSTANCE_NAME`` pointed at whatever instance was
    created last, which (if sourced) overrides the pointer. Setting both
    keeps them in agreement."""
    target = args.name.strip()
    if not target:
        print(c.red("instance name cannot be empty"))
        return 1
    instances = {p.name: p for p in c.list_known_instances()}
    if target not in instances:
        print(c.red(f"no instance named {target!r}"))
        print(c.dim(f"known: {', '.join(sorted(instances)) or '(none)'}"))
        return 1

    from jaeger_os.core.instance.instance import write_active_instance
    write_active_instance(target)
    try:
        from jaeger_os.core.instance.setup_wizard import _write_env_file
        _write_env_file(instances[target], target)
    except Exception:  # noqa: BLE001 — env pin is a convenience
        pass
    print(c.green(f"default agent → {target!r}"))
    print(c.dim(f"`jaeger` now runs {target!r}; "
                f"`jaeger --instance NAME` for others."))
    return 0


# back-compat: ``switch`` is an alias of ``set-default``.
run_switch = run_set_default


# ── create / edit (the wizard) ─────────────────────────────────────

def run_create(args: Any) -> int:
    """Create a new instance via the setup wizard."""
    name = getattr(args, "name", None)
    from jaeger_os.core.instance.setup_wizard import run_wizard
    run_wizard(force=False, instance_name=name, boot_after=False)
    return 0


def run_edit(args: Any) -> int:
    """Reconfigure an existing instance — re-runs the wizard against it.
    Keeps the instance's memory/skills; rewrites identity + config."""
    name = args.name.strip()
    known = {p.name for p in c.list_known_instances()}
    if name not in known:
        print(c.red(f"no instance named {name!r}"))
        print(c.dim(f"known: {', '.join(sorted(known)) or '(none)'}"))
        return 1
    from jaeger_os.core.instance.setup_wizard import run_wizard
    run_wizard(force=True, instance_name=name, boot_after=False)
    return 0


# ── delete ─────────────────────────────────────────────────────────

def run_delete(args: Any) -> int:
    """Delete an instance directory. Type-to-confirm unless ``--yes``."""
    import shutil

    name = args.name.strip()
    instances = {p.name: p for p in c.list_known_instances()}
    if name not in instances:
        print(c.red(f"no instance named {name!r}"))
        print(c.dim(f"known: {', '.join(sorted(instances)) or '(none)'}"))
        return 1
    inst_dir = instances[name]
    if not getattr(args, "yes", False):
        print(c.yellow(f"  about to delete instance {name!r}:"))
        print(c.dim(f"    {inst_dir}"))
        if input(f"  type {name!r} to confirm: ").strip() != name:
            print(c.dim("  cancelled"))
            return 1
    shutil.rmtree(inst_dir, ignore_errors=True)
    from jaeger_os.core.instance.instance import (
        read_active_instance, write_active_instance,
    )
    if read_active_instance() == name:
        write_active_instance(None)   # don't leave a dangling default
    print(c.green(f"deleted {name!r}"))
    return 0
