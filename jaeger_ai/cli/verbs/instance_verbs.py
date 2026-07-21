"""CLI verbs for instance lifecycle (INST-2 in docs/ROADMAP_0.2.0.md).

The daemon dispatcher (``daemon/cli.py``) peels these off before its
own argparse so they can have their own flag surface without
fighting the lifecycle parser.

Verbs added in 0.2.0:

  jaeger setup [--name N] [--force]
      Run the wizard (interactive). Creates a NEW instance or rebuilds
      an existing one (with the wizard's standard backup-aside). The
      old ``--setup`` / ``--create-instance`` flags were removed in
      0.2.0 — this verb is the only entry point.

  jaeger instance list
      Print every instance under ``~/.jaeger/instances/`` with its
      identity summary; the active one is starred.

  jaeger instance use <name>
      Write ``~/.jaeger/active_instance`` — the sticky default the
      resolver consults when no env var or CLI flag is set.

  jaeger instance inspect <name>
      Dump identity + config + manifest WITHOUT booting the model.

  jaeger instance delete <name> [--force]
      Remove the whole instance dir (asks for confirmation).

  jaeger instance clear <name> [--force]
      Wipe memory + logs but keep identity / config / skills /
      credentials.

  jaeger migrate
      Run pending per-instance migrations on the active instance.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# ── helpers ────────────────────────────────────────────────────────


def _print_setup_usage() -> None:
    print(
        "usage: jaeger setup [--name NAME] [--force]\n"
        "\n"
        "  Run the interactive setup wizard. Bareword `jaeger setup`\n"
        "  operates on the active instance (env / sticky / 'default').\n"
        "\n"
        "  --name NAME  the instance folder AND the default for Step 1's\n"
        "               agent-name prompt (editable there — the agent's\n"
        "               name is never forced to match the folder). With\n"
        "               no --name, Step 1 defaults to your character\n"
        "               pick instead, and the folder is named from\n"
        "               whatever you type.\n"
        "  --force      rebuild an existing instance (wizard backs up\n"
        "               the old contents to <name>.bak.<ts> first).\n",
        file=sys.stderr,
    )


def _print_instance_usage() -> None:
    print(
        "usage: jaeger instance <verb> [args...]\n"
        "\n"
        "verbs:\n"
        "  list                    show every instance under ~/.jaeger/instances/\n"
        "  use <name>              set the sticky default (~/.jaeger/active_instance)\n"
        "  inspect <name>          print identity + config + manifest (no boot)\n"
        "  delete <name> [-f]      remove an instance dir (asks unless --force)\n"
        "  clear <name>  [-f]      wipe memory + logs; keep identity / config\n",
        file=sys.stderr,
    )


def _print_agent_usage() -> None:
    print(
        "usage: jaeger agent <command> [args...]\n"
        "\n"
        "  An agent is a deployed AI that plays a character — its own memory,\n"
        "  config, and model. (The character is the persona; the agent runs it.)\n"
        "\n"
        "commands:\n"
        "  create [--name NAME] [--tui]\n"
        "                           create an agent — the app's setup window\n"
        "                           when built; --tui for the terminal wizard.\n"
        "                           NAME becomes the agent's name (editable in\n"
        "                           the wizard, never forced by a character\n"
        "                           pick); the wizard defaults to your\n"
        "                           character pick when NAME is omitted.\n"
        "  create [--name NAME] --force\n"
        "                           rebuild an existing agent (terminal wizard)\n"
        "  list                     show every agent (active one starred)\n"
        "  use <name>               set the default agent\n"
        "  inspect <name>           print identity + config (no model boot)\n"
        "  delete <name> [-f]       remove an agent\n"
        "  clear <name>  [-f]       wipe an agent's memory + logs (keep identity)\n"
        "\n"
        "  (`jaeger instance` / `jaeger setup` remain as aliases.)\n",
        file=sys.stderr,
    )


# ── ``jaeger setup`` ───────────────────────────────────────────────


def _cmd_setup_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger setup", add_help=False)
    parser.add_argument("--name", default=None,
                        help="instance name (default: pick from env / sticky / 'default')")
    parser.add_argument("--force", action="store_true",
                        help="rebuild an existing instance (wizard backs up first)")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        _print_setup_usage()
        return 0

    from jaeger_ai.core.instance.setup_wizard import run_wizard
    try:
        run_wizard(force=args.force, instance_name=args.name)
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger setup] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


# ── ``jaeger migrate`` ─────────────────────────────────────────────


def _cmd_migrate_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger migrate", add_help=False)
    parser.add_argument("--instance", "--agent", default=None, dest="instance",
                        help="agent name (default: active)")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print("usage: jaeger migrate [--instance NAME]\n", file=sys.stderr)
        return 0

    from jaeger_ai.core.instance.instance import (
        InstanceLayout, default_instance_name, resolve_instance_dir,
    )
    from jaeger_ai.core.instance.migrations import run_pending_migrations

    name = args.instance or default_instance_name()
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.exists():
        print(f"[jaeger migrate] instance {name!r} not found at {layout.root}.",
              file=sys.stderr)
        return 1

    try:
        applied = run_pending_migrations(layout)
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger migrate] failed: {exc}", file=sys.stderr)
        return 2

    if not applied:
        print(f"[jaeger migrate] {name!r}: already at the installed core version "
              "— nothing to do.")
    else:
        print(f"[jaeger migrate] {name!r}: applied {len(applied)} migration(s):")
        for name in applied:
            print(f"  ✓ {name}")
    return 0


# ── ``jaeger instance ...`` group ──────────────────────────────────


def _cmd_instance_argv(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        _print_instance_usage()
        return 0 if argv else 2

    verb = argv[0]
    rest = argv[1:]
    if verb == "list":
        return _instance_list(rest)
    if verb == "use":
        return _instance_use(rest)
    if verb == "inspect":
        return _instance_inspect(rest)
    if verb == "delete":
        return _instance_delete(rest)
    if verb == "clear":
        return _instance_clear(rest)
    print(f"[jaeger instance] unknown verb {verb!r}", file=sys.stderr)
    _print_instance_usage()
    return 2


def _cmd_agent_argv(argv: list[str]) -> int:
    """``jaeger agent ...`` — the operator-facing name for the agents you
    deploy (each plays a character; its own memory/config/model). Thin
    front-end over the instance machinery; ``jaeger instance`` / ``jaeger
    setup`` stay as aliases. Internally these are still 'instances'."""
    if not argv or argv[0] in ("-h", "--help"):
        _print_agent_usage()
        return 0 if argv else 2
    verb, rest = argv[0], list(argv[1:])
    if verb == "create":
        # Friendly positional: `agent create <name>` → setup --name <name>.
        if rest and not rest[0].startswith("-"):
            rest = ["--name", rest[0], *rest[1:]]
        # 0.7.1 GUI-first: creating an agent opens the Swift app's setup
        # window when the product app is built and the target instance
        # doesn't exist yet — the app pins JAEGER_INSTANCE_NAME, the
        # bridge reports ``no_instance``, and onboarding takes over.
        # ``jaeger setup`` routes here too (0.9.6 — GUI-first everywhere);
        # ``--tui`` (`jaeger setup tui`) / ``--force`` / headless keep
        # the terminal wizard.
        if "--tui" in rest:
            rest.remove("--tui")
            return _cmd_setup_argv(rest)
        if "--force" not in rest and not os.environ.get("JAEGER_NO_GUI"):
            from jaeger_ai.core.instance.instance import (
                InstanceLayout, default_instance_name, resolve_instance_dir,
            )
            from jaeger_ai.main import _launch_swift_app, _swift_app_binary
            name = default_instance_name()
            if "--name" in rest and rest.index("--name") + 1 < len(rest):
                name = rest[rest.index("--name") + 1]
            app = _swift_app_binary()
            if (app is not None
                    and not InstanceLayout(
                        root=resolve_instance_dir(name)).exists()):
                return _launch_swift_app(app, name)
        return _cmd_setup_argv(rest)
    if verb in ("list", "use", "inspect", "delete", "clear"):
        return _cmd_instance_argv(argv)   # argv[0] is the verb
    print(f"[jaeger agent] unknown command {verb!r}", file=sys.stderr)
    _print_agent_usage()
    return 2


def _instance_list(argv: list[str]) -> int:
    from jaeger_ai.core.instance.instance import (
        active_instance_path, default_instance_name, read_active_instance,
        user_instances_root,
    )
    from jaeger_ai.core.instance.schemas import Identity, load_yaml

    root = user_instances_root()
    print(f"Instances under {root}:")
    if not root.exists():
        print("  (none yet — run `./run.sh setup` to create one)")
        return 0

    instances = sorted(
        p for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
    if not instances:
        print("  (none yet — run `./run.sh setup` to create one)")
        return 0

    active = default_instance_name()
    sticky = read_active_instance()
    env = ((__import__("os").environ.get("JAEGER_INSTANCE_NAME") or "").strip()
           or None)
    for path in instances:
        name = path.name
        marker = " *" if name == active else "  "
        summary: str
        if (path / "identity.yaml").exists():
            try:
                identity = load_yaml(path / "identity.yaml", Identity)
                summary = f"{identity.name!r} — {identity.role}"
            except Exception:  # noqa: BLE001
                summary = "(unreadable identity.yaml)"
        else:
            summary = "(stub: no identity.yaml — partial setup?)"
        print(f"{marker} {name:<24} {summary}")

    print()
    print(f"* = active ({_explain_active(env, sticky)})")
    return 0


def _explain_active(env: str | None, sticky: str | None) -> str:
    if env:
        return f"JAEGER_INSTANCE_NAME={env!r}"
    if sticky:
        return f"sticky default — see {Path('~/.jaeger/active_instance').expanduser()}"
    return "literal 'default'"


# ── interactive instance picker ───────────────────────────────────


def _list_local_instances() -> list[str]:
    """Return every directory name under ``~/.jaeger/instances/`` that
    looks like a real instance (has identity.yaml). Used by the bareword
    verbs to offer a picker."""
    from jaeger_ai.core.instance.instance import user_instances_root
    root = user_instances_root()
    if not root.exists():
        return []
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if (p / "identity.yaml").exists():
            out.append(p.name)
    return out


def _pick_instance_interactively(prompt: str = "Which instance?") -> str | None:
    """Numbered picker — used when a verb is invoked bareword and we
    need a name. Returns the chosen name, or ``None`` if the user
    bailed / stdin is closed / no instances exist."""
    names = _list_local_instances()
    if not names:
        print("[jaeger] no instances found under ~/.jaeger/instances/.",
              file=sys.stderr)
        print("         run `./run.sh setup` to create one.", file=sys.stderr)
        return None
    if len(names) == 1:
        # Single-choice — no prompt; just pick it.
        return names[0]
    if not sys.stdin.isatty():
        print(f"[jaeger] {len(names)} instances; specify one explicitly "
              "(stdin is not a tty).", file=sys.stderr)
        return None

    from jaeger_ai.core.instance.instance import default_instance_name
    active = default_instance_name()
    print(prompt)
    for i, n in enumerate(names):
        marker = "›" if n == active else " "
        print(f"     {marker} {i + 1}. {n}")
    while True:
        raw = input(f"  Pick 1-{len(names)} (Enter = {active}): ").strip()
        if not raw:
            return active if active in names else names[0]
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(names):
                return names[idx - 1]
        if raw in names:
            return raw
        print(f"     (pick 1-{len(names)} or type a name; ^C to abort)")


def _instance_use(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("usage: jaeger instance use [<name>]\n"
              "  Bareword: prompts to pick from available instances.",
              file=sys.stderr)
        return 0

    if not argv:
        # Bareword: prompt to pick.
        name = _pick_instance_interactively("Which instance should become the sticky default?")
        if name is None:
            return 1
    else:
        name = argv[0].strip()
        if not name:
            print("[jaeger instance use] name is empty", file=sys.stderr)
            return 2

    from jaeger_ai.core.instance.instance import (
        active_instance_path, user_instances_root, write_active_instance,
    )
    target = user_instances_root() / name
    if not target.exists():
        print(f"[jaeger instance use] no instance {name!r} at {target}",
              file=sys.stderr)
        print("                       run `./run.sh setup " + name +
              "` to create it.", file=sys.stderr)
        return 1

    write_active_instance(name)
    print(f"[jaeger instance use] sticky default set to {name!r}")
    print(f"                      ({active_instance_path()})")
    return 0


def _instance_inspect(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("usage: jaeger instance inspect [<name>]\n"
              "  Bareword: inspects the active instance.",
              file=sys.stderr)
        return 0

    if not argv:
        from jaeger_ai.core.instance.instance import default_instance_name
        name = default_instance_name()
    else:
        name = argv[0]
    from jaeger_ai.core.instance.instance import (
        InstanceLayout, resolve_instance_dir,
    )
    from jaeger_ai.core.instance.schemas import (
        Config, Identity, Manifest, load_json, load_yaml,
    )

    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.exists():
        print(f"[jaeger instance inspect] no instance {name!r} at {layout.root}",
              file=sys.stderr)
        return 1

    print(f"# instance {name!r}")
    print(f"  path: {layout.root}")
    print()
    # Identity
    try:
        identity = load_yaml(layout.identity_path, Identity)
        print("# identity.yaml")
        print(f"  name:        {identity.name}")
        print(f"  role:        {identity.role}")
        print(f"  personality: {identity.personality}")
        print(f"  voice:       {identity.voice_id or '(unset)'}")
    except Exception as exc:  # noqa: BLE001
        print(f"# identity.yaml — unreadable: {exc}")
    print()
    # Config
    try:
        cfg = load_yaml(layout.config_path, Config)
        print("# config.yaml")
        print(f"  model:        {cfg.model.model_path}")
        print(f"  ctx:          {cfg.model.ctx}")
        print(f"  permissions:  {cfg.permissions.mode}")
        print(f"  interaction:  {cfg.interaction.default_mode}")
        print(f"  voice:        {'on' if cfg.voice.enabled else 'off'}")
    except Exception as exc:  # noqa: BLE001
        print(f"# config.yaml — unreadable: {exc}")
    print()
    # Manifest
    try:
        manifest = load_json(layout.manifest_path, Manifest)
        print("# manifest.json")
        print(f"  schema_version:  {manifest.schema_version}")
        print(f"  created_at:      {manifest.created_at}")
        print(f"  last_started_at: {manifest.last_started_at or '(never)'}")
    except Exception as exc:  # noqa: BLE001
        print(f"# manifest.json — unreadable: {exc}")
    print()
    # Distribution (optional — exists post-INST-3)
    dist_path = layout.root / "distribution.yaml"
    if dist_path.exists():
        try:
            from jaeger_ai.core.instance.schemas import DistributionConfig
            dist = load_yaml(dist_path, DistributionConfig)
            print("# distribution.yaml")
            print(f"  install_method:                 {dist.install_method}")
            print(f"  created_with_framework:         {dist.created_with_framework}")
            print(f"  last_updated_with_framework:    {dist.last_updated_with_framework}")
            if dist.install_source:
                print(f"  install_source:                 {dist.install_source}")
            if getattr(dist, "restored_from", None):
                print(f"  restored_from:                  {dist.restored_from}")
        except Exception as exc:  # noqa: BLE001
            print(f"# distribution.yaml — unreadable: {exc}")
    return 0


def _instance_delete(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger instance delete",
                                     add_help=False)
    parser.add_argument("name", nargs="?", default=None)
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print("usage: jaeger instance delete [<name>] [-f|--force]\n"
              "  Bareword: prompts to pick from available instances.",
              file=sys.stderr)
        return 0

    if args.name is None:
        picked = _pick_instance_interactively("Which instance to DELETE?")
        if picked is None:
            return 1
        args.name = picked

    from jaeger_ai.core.instance.instance import (
        InstanceLayout, default_instance_name, read_active_instance,
        resolve_instance_dir, write_active_instance,
    )

    name = args.name
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.root.exists():
        print(f"[jaeger instance delete] no instance {name!r} — nothing to delete.")
        return 1

    if name == default_instance_name() and not args.force:
        print(f"[jaeger instance delete] {name!r} is the active instance. "
              f"Pass --force to delete it anyway.", file=sys.stderr)
        return 2

    if not args.force:
        if sys.stdin.isatty():
            confirm = input(
                f"[jaeger instance delete] delete instance {name!r} at "
                f"{layout.root}? Type the name to confirm: "
            )
            if confirm.strip() != name:
                print("[jaeger instance delete] aborted (name didn't match).")
                return 1
        else:
            print("[jaeger instance delete] non-interactive — pass --force.",
                  file=sys.stderr)
            return 2

    import shutil
    shutil.rmtree(layout.root)
    # If this was the sticky default, clear it so the resolver
    # doesn't keep pointing at a missing instance.
    if read_active_instance() == name:
        write_active_instance(None)
        print(f"[jaeger instance delete] also cleared sticky default "
              f"(was pointing at {name!r}).")
    print(f"[jaeger instance delete] deleted {name!r}.")
    return 0


def _instance_clear(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger instance clear",
                                     add_help=False)
    parser.add_argument("name", nargs="?", default=None)
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print("usage: jaeger instance clear [<name>] [-f|--force]\n"
              "  Wipes memory + logs; keeps identity / config / credentials / skills.\n"
              "  Bareword: prompts to pick from available instances.",
              file=sys.stderr)
        return 0

    if args.name is None:
        picked = _pick_instance_interactively("Which instance to CLEAR (memory + logs)?")
        if picked is None:
            return 1
        args.name = picked

    from jaeger_ai.core.instance.instance import (
        InstanceLayout, resolve_instance_dir,
    )

    name = args.name
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.root.exists():
        print(f"[jaeger instance clear] no instance {name!r} — nothing to clear.")
        return 1

    if not args.force:
        if sys.stdin.isatty():
            confirm = input(
                f"[jaeger instance clear] wipe memory + logs for {name!r}? "
                f"(identity / config / credentials / skills are preserved) [y/N]: "
            )
            if confirm.strip().lower() not in ("y", "yes"):
                print("[jaeger instance clear] aborted.")
                return 1
        else:
            print("[jaeger instance clear] non-interactive — pass --force.",
                  file=sys.stderr)
            return 2

    import shutil
    for sub in ("memory", "logs"):
        p = layout.root / sub
        if p.exists():
            shutil.rmtree(p)
            p.mkdir()
            (p / ".gitkeep").touch()
    print(f"[jaeger instance clear] cleared memory + logs for {name!r}.")
    return 0


__all__ = [
    "_cmd_setup_argv",
    "_cmd_instance_argv",
    "_cmd_migrate_argv",
]
