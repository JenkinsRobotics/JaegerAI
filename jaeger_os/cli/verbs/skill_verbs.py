"""``jaeger skill ...`` — inspect + clone bundled skills.

Two verbs:

  jaeger skill list
      List every skill the framework knows about, with its zone
      (``bundled`` from ``site-packages/jaeger_os/skills/``, or
      ``instance`` from ``<instance>/skills/``). The active resolver
      uses instance-wins-on-collision, so this view shows which copy
      the agent actually sees.

  jaeger skill clone <name>
      Copy a bundled skill into the active instance's skills dir so
      the user (or the agent itself) can edit it freely without
      touching the framework install. Once cloned, the instance copy
      shadows the bundled one (instance-wins resolver behaviour).
      Existing instance-zone skills are never overwritten.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _cmd_skill_argv(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger skill <verb> [args...]\n"
            "\n"
            "verbs:\n"
            "  list                       show every skill + its zone\n"
            "  clone <name>               copy a bundled skill into the\n"
            "                             active instance for editing\n",
            file=sys.stderr,
        )
        return 0 if argv else 2

    verb = argv[0]
    rest = argv[1:]
    if verb == "list":
        return _skill_list(rest)
    if verb == "clone":
        return _skill_clone(rest)
    print(f"[jaeger skill] unknown verb {verb!r}", file=sys.stderr)
    return 2


def _skill_list(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger skill list", add_help=False)
    parser.add_argument("--instance", "--agent", default=None, dest="instance",
                        help="agent name (default: active)")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print("usage: jaeger skill list [--instance NAME]", file=sys.stderr)
        return 0

    from jaeger_os.core.instance.instance import (
        InstanceLayout, default_instance_name, resolve_instance_dir,
    )
    name = args.instance or default_instance_name()
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.exists():
        print(f"[jaeger skill list] no instance {name!r} at {layout.root}",
              file=sys.stderr)
        return 1

    # Tool-skills (the ``<name>_v<N>`` pattern) — discovered by the
    # skill loader with instance-wins-on-collision merge.
    from jaeger_os.agent.skill_registry.skill_loader import discover_skills
    tool_skills = discover_skills(layout)
    print(f"# Tool-skills (active resolver) — instance {name!r}")
    if not tool_skills:
        print("  (none)")
    else:
        for s in tool_skills:
            zone = "[instance]" if s.zone == "instance" else "[bundled] "
            print(f"  {zone}  {s.name}_v{s.version}  {s.folder}")

    # Playbook skills — markdown procedures the agent reads via
    # skill(action="view"). Loaded by playbook_skills.
    print()
    print(f"# Playbook skills (loaded via skill(action='view'))")
    try:
        from jaeger_os.agent.skill_registry import playbook_skills as _pb
        playbooks = _pb.available_playbooks()
    except Exception as exc:  # noqa: BLE001
        print(f"  (couldn't load playbook list: {exc})", file=sys.stderr)
        return 0
    if not playbooks:
        print("  (none)")
    else:
        for p in playbooks:
            print(f"  [{p.origin:<8}]  {p.name:<32} ({p.category})")
    return 0


def _skill_clone(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger skill clone", add_help=False)
    parser.add_argument("name", nargs="?", default=None)
    parser.add_argument("--instance", "--agent", default=None, dest="instance",
                        help="agent name (default: active)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing instance-zone copy")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help or args.name is None:
        print(
            "usage: jaeger skill clone <name> [--instance NAME] [--force]\n"
            "\n"
            "  Copy a bundled skill into the active instance for editing.\n"
            "  Once cloned, the instance copy shadows the bundled one.\n"
            "  Refuses to overwrite an existing instance-zone copy\n"
            "  unless --force.\n",
            file=sys.stderr,
        )
        return 0 if args.help else 2

    from jaeger_os.core.instance.instance import (
        InstanceLayout, default_instance_name, resolve_instance_dir,
    )
    from jaeger_os.agent.skill_registry.skill_loader import (
        CORE_SKILLS_DIR, _scan_zone,
    )

    inst_name = args.instance or default_instance_name()
    layout = InstanceLayout(root=resolve_instance_dir(inst_name))
    if not layout.exists():
        print(f"[jaeger skill clone] no instance {inst_name!r} at {layout.root}",
              file=sys.stderr)
        return 1

    # Find the bundled tool-skill (the only kind that fits the
    # ``<name>_v<N>`` clone shape). Playbook skills are nested
    # under category dirs and easier to copy by hand than to
    # cookie-cutter into the instance layout.
    bundled = _scan_zone(CORE_SKILLS_DIR, "core")
    matches = [s for s in bundled if s.name == args.name]
    if not matches:
        print(f"[jaeger skill clone] no bundled skill named {args.name!r}.",
              file=sys.stderr)
        print("                     run `jaeger skill list` to see options.",
              file=sys.stderr)
        # Hint about playbook skills, which require a manual cp.
        try:
            from jaeger_os.agent.skill_registry import playbook_skills as _pb
            pb_match = next(
                (p for p in _pb.available_playbooks() if p.name == args.name),
                None,
            )
            if pb_match is not None:
                src = pb_match.path.parent
                dst = layout.skills_dir / pb_match.name
                print(f"                     {args.name!r} is a playbook skill — "
                      f"copy manually:", file=sys.stderr)
                print(f"                       cp -r {src} {dst}",
                      file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass
        return 1

    # Pick the highest version (matches the loader's "best in zone").
    src_skill = max(matches, key=lambda s: s.version)
    src = src_skill.folder
    dst = layout.skills_dir / f"{src_skill.name}_v{src_skill.version}"

    if dst.exists():
        if not args.force:
            print(f"[jaeger skill clone] instance copy already exists at "
                  f"{dst}.", file=sys.stderr)
            print("                     pass --force to overwrite, or "
                  "rename the existing dir.", file=sys.stderr)
            return 1
        shutil.rmtree(dst)

    layout.skills_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    print(f"[jaeger skill clone] cloned {src} → {dst}")
    print(f"                     edit files there; the resolver picks the "
          f"instance copy over the bundled one on next agent boot.")
    return 0


__all__ = ["_cmd_skill_argv"]
