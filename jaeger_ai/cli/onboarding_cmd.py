"""``jaeger onboarding status|reset`` — inspect and clear OS 1 first boot.

Reset is deliberately narrow. It removes the welcome record and nothing
else, so the two questions run again on the next boot while memory, the
Library, projects, credentials, provider settings and the character sheet
all survive untouched. Wiping those is a different and far more
consequential operation, and it is not reachable from here by accident:
this verb prints exactly what it will and will not touch, and requires
confirmation unless ``--yes`` is passed.

``status`` is the developer-facing view of §24 observability — current
state, schema version, whether the identity was migrated rather than
walked through the welcome, and which answers are on record.
"""

from __future__ import annotations

import argparse
import json
import sys

USAGE = "jaeger onboarding <status|reset> [--instance NAME] [--yes] [--json]"


def _layout(instance: str | None):
    from jaeger_ai.core.instance.instance import (
        InstanceLayout,
        default_instance_name,
        resolve_instance_dir,
    )

    name = instance or default_instance_name()
    return InstanceLayout(resolve_instance_dir(name)), name


def _cmd_status(args: argparse.Namespace) -> int:
    from jaeger_ai.core.instance import first_boot as fb

    layout, name = _layout(args.instance)
    snap = fb.snapshot(layout)

    if args.json:
        print(json.dumps({"instance": name, **snap}, indent=2, sort_keys=True))
        return 0

    print(f"  instance        {name}")
    print(f"  status          {snap.get('status')}")
    print(f"  schema_version  {snap.get('schema_version')}")
    print(f"  state file      {fb.state_path(layout)}")
    if snap.get("migrated"):
        print(f"  migrated        yes ({snap.get('migration_reason')})")
    for key, label in (
        ("started_at", "started"),
        ("completed_at", "completed"),
        ("voice_profile", "voice"),
        ("persona_name", "persona name"),
    ):
        if snap.get(key):
            print(f"  {label:<15} {snap[key]}")
    if snap.get("q2_refused"):
        print("  question 2      declined (recorded, not re-asked)")
    elif snap.get("q2_response"):
        print("  question 2      answered")
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    from jaeger_ai.core.instance import first_boot as fb

    layout, name = _layout(args.instance)
    path = fb.state_path(layout)

    print(f"  Reset OS 1 first boot for instance '{name}'.")
    print()
    print("  This clears ONLY the welcome record:")
    print(f"    {path}")
    print()
    print("  The next start will ask the two baseline questions again.")
    print("  NOT touched — memory, Library, projects, credentials,")
    print("  provider settings, sessions, skills, or the character sheet.")
    print()

    if not path.is_file():
        # NOT a no-op. An absent state file is exactly the case
        # ``ensure_migrated`` reads as "this identity predates onboarding"
        # and marks COMPLETED — so on an established install, returning
        # early here leaves the welcome suppressed while telling the
        # operator the reset succeeded. Fall through and write the explicit
        # NOT_STARTED marker, which is what actually overrides the guard.
        print("  No existing record — writing an explicit reset marker")
        print("  so the migration guard cannot re-suppress the welcome.")
        print()

    if not args.yes:
        try:
            answer = input("  Proceed? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return 1
        if answer not in {"y", "yes"}:
            print("  Cancelled.")
            return 1

    fb.reset(layout)
    print("  First-boot state cleared.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jaeger onboarding", usage=USAGE)
    parser.add_argument("action", choices=("status", "reset"))
    parser.add_argument("--instance", default=None)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--json", action="store_true", help="machine-readable status")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return _cmd_status(args) if args.action == "status" else _cmd_reset(args)


if __name__ == "__main__":  # pragma: no cover — process entry point
    raise SystemExit(main())
