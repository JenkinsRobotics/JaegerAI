#!/usr/bin/env python3
"""Plugins probe — health-check every plugin from the CLI.

The "are the plugins actually working?" check a human can run. For each plugin
it prints library status + the list_plugins status, flags any with an
un-importable library, and prints the remaining setup steps for any that aren't
ready yet. Exit code is non-zero if any plugin has a broken (missing) library.

    .venv/bin/python dev/pipelines/plugins.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from jaeger_os.agent.tools.plugins import list_plugins, setup_plugin  # noqa: E402


def main() -> int:
    plugins = list_plugins().get("plugins", [])
    if not plugins:
        print("no plugins found under jaeger_os/plugins/")
        return 1

    broken = 0
    print(f"{'plugin':16} {'status':22} libraries")
    print("-" * 64)
    for p in plugins:
        name = str(p.get("name", "?"))
        status = str(p.get("status", "?"))
        libs = p.get("libraries") or {}
        missing = [lib for lib, ok in libs.items() if not ok]
        flag = "LIB!" if missing else " ok "
        if missing:
            broken += 1
        print(f"[{flag}] {name:16} {status:22} {libs}")
        if missing:
            print(f"         missing (install first): {missing}")

    print("-" * 64)
    print(f"{len(plugins)} plugins · {len(plugins) - broken} library-healthy · {broken} broken")

    # What's left to finish setup for the ones that aren't ready.
    for p in plugins:
        if p.get("status") != "ready":
            res = setup_plugin(str(p.get("name")))
            steps = res.get("steps") or []
            if steps:
                print(f"\n{p.get('name')} — to finish setup:")
                for step in steps:
                    print(f"  • {step}")

    print("\nThe agent activates a messaging bridge with activate_plugin(<name>) "
          "(or /plugins activate <name>, or the Studio Settings → Plugins button) "
          "once its credential is saved via set_credential.")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
