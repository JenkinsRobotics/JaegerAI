"""``jaeger settings`` — view + change agent settings from the terminal.

Terminal-first by design: every setting the Swift app exposes is reachable
here, because BOTH surfaces read the ONE schema-derived catalog
(``core/settings/catalog.py``). A setting is defined once as an annotated
``Field`` in ``core/instance/schemas.py`` and appears in both places.

  jaeger settings list [--group G] [--advanced]   every setting + value
  jaeger settings groups                           the group index + counts
  jaeger settings get <path>                       one setting's detail
  jaeger settings set <path> <value>               validate + persist a change
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from jaeger_ai.cli import _common as c


def _cmd_settings_argv(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger settings <verb> [args...]\n"
            "\n"
            "verbs:\n"
            "  list [--group G] [--advanced]   every setting, value + default\n"
            "  groups                          the settings groups + counts\n"
            "  get <path>                      one setting's full detail\n"
            "  set <path> <value>              validate + persist a change\n"
            "\n"
            "  common: --instance/-i NAME to target a specific agent.\n"
            "  e.g. jaeger settings set voice.speak_replies false\n",
            file=sys.stderr,
        )
        return 0 if argv else 2

    verb, rest = argv[0], argv[1:]
    if verb == "list":
        return _settings_list(rest)
    if verb == "groups":
        return _settings_groups(rest)
    if verb == "get":
        return _settings_get(rest)
    if verb == "set":
        return _settings_set(rest)
    print(f"[jaeger settings] unknown verb {verb!r}", file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
def _resolve_layout(instance: str | None) -> Any:
    from jaeger_ai.core.instance.instance import (
        InstanceLayout, default_instance_name, resolve_instance_dir)
    name = instance or default_instance_name()
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.exists():
        print(c.red(f"  no instance {name!r} at {layout.root} — "
                    "run `jaeger agent create` first"), file=sys.stderr)
        return None
    return layout


def _fmt_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return repr(v) if (v == "" or " " in v) else v
    return str(v)


def _fmt_type(d: dict[str, Any]) -> str:
    if d["type"] == "enum":
        return "{" + " | ".join(str(x) for x in d.get("choices", [])) + "}"
    val = d.get("validation") or {}
    bounds = ""
    if "min" in val or "max" in val:
        bounds = f" [{val.get('min', '')}..{val.get('max', '')}]"
    return d["type"] + bounds


# ---------------------------------------------------------------------------
def _settings_list(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="jaeger settings list", add_help=False)
    p.add_argument("--group", default=None)
    p.add_argument("--advanced", action="store_true",
                   help="include advanced settings")
    p.add_argument("--instance", "-i", "--agent", dest="instance", default=None)
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args(argv)
    if args.help:
        print("usage: jaeger settings list [--group G] [--advanced] "
              "[--instance NAME]", file=sys.stderr)
        return 0
    layout = _resolve_layout(args.instance)
    if layout is None:
        return 1

    from jaeger_ai.core.settings.catalog import catalog
    grouped = catalog(layout, advanced=args.advanced, group=args.group)
    if not grouped:
        print(c.dim(f"  no settings in group {args.group!r}"
                    if args.group else "  no settings exposed"))
        return 0

    print()
    print(f"  {c.bold('Settings')}  ·  instance {c.cyan(layout.root.name)}")
    print(c.dim("  ✱ overridden from default   ·   ⟳ restart required"
                "   ·   --advanced for tuning knobs"))
    for group, items in grouped.items():
        print()
        print(f"  {c.bold(group.upper())}")
        for d in items:
            star = c.cyan("✱") if d["current"] != d["default"] else " "
            restart = c.yellow("⟳") if d["restart"] else " "
            print(f"    {star}{restart} {d['path']:<30} "
                  f"= {c.bold(_fmt_value(d['current']))}  "
                  f"{c.dim(_fmt_type(d))}")
    print()
    return 0


def _settings_groups(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="jaeger settings groups", add_help=False)
    p.add_argument("--instance", "-i", "--agent", dest="instance", default=None)
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args(argv)
    if args.help:
        print("usage: jaeger settings groups [--instance NAME]", file=sys.stderr)
        return 0
    layout = _resolve_layout(args.instance)
    if layout is None:
        return 1
    from jaeger_ai.core.settings.catalog import groups
    print()
    print(f"  {c.bold('Settings groups')}  ·  instance {c.cyan(layout.root.name)}")
    print()
    for g in groups(layout):
        print(f"    {g['name']:<16} {c.dim(str(g['count']) + ' settings')}")
    print()
    print(c.dim("  jaeger settings list --group <name>"))
    print()
    return 0


def _settings_get(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="jaeger settings get", add_help=False)
    p.add_argument("path", nargs="?", default=None)
    p.add_argument("--instance", "-i", "--agent", dest="instance", default=None)
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args(argv)
    if args.help or args.path is None:
        print("usage: jaeger settings get <path> [--instance NAME]",
              file=sys.stderr)
        return 0 if args.help else 2
    layout = _resolve_layout(args.instance)
    if layout is None:
        return 1
    from jaeger_ai.core.settings.catalog import describe
    d = describe(layout, args.path)
    if d is None:
        print(c.red(f"  unknown setting: {args.path!r} — "
                    "`jaeger settings list` shows every path"), file=sys.stderr)
        return 1
    print()
    print(f"  {c.bold(d['path'])}   {c.dim('(' + d['group'] + ')')}")
    print(f"    value    {c.bold(_fmt_value(d['current']))}")
    print(f"    default  {_fmt_value(d['default'])}")
    print(f"    type     {_fmt_type(d)}")
    if d["restart"]:
        print(f"    {c.yellow('restart required for changes to take effect')}")
    if d["advanced"]:
        print(c.dim("    advanced"))
    if d["description"]:
        import textwrap
        print()
        for line in textwrap.wrap(d["description"], width=72):
            print(c.dim(f"    {line}"))
    print()
    return 0


def _settings_set(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="jaeger settings set", add_help=False)
    p.add_argument("path", nargs="?", default=None)
    p.add_argument("value", nargs="?", default=None)
    p.add_argument("--instance", "-i", "--agent", dest="instance", default=None)
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args(argv)
    if args.help or args.path is None or args.value is None:
        print("usage: jaeger settings set <path> <value> [--instance NAME]\n"
              "  e.g. jaeger settings set voice.speak_replies false",
              file=sys.stderr)
        return 0 if args.help else 2
    layout = _resolve_layout(args.instance)
    if layout is None:
        return 1
    from jaeger_ai.core.settings.catalog import set_value
    try:
        res = set_value(layout, args.path, args.value)
    except (ValueError, KeyError) as exc:
        print(c.red(f"  {exc}"), file=sys.stderr)
        return 1
    print(c.green(f"  set {res['path']} = {_fmt_value(res['value'])}"))
    if res["restart_required"]:
        print(c.yellow("  restart the agent for this to take effect"))
    return 0


__all__ = ["_cmd_settings_argv"]
