"""``jaeger uninstall`` — remove the framework, keep or wipe agents.

Mirrors the install's two-bucket split: removes the *framework* (the product
files + ``.venv``) and by default KEEPS ``.jaeger_os/`` (every agent's persona,
memory, skills, credentials). ``--purge`` wipes that too (irreversible).

Refuses on a dev clone (a ``.git`` at the install root) — uninstalling your
working checkout is never what you want; remove it by hand.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from jaeger_ai.cli.verbs.update_verb import _PRODUCT

# Framework = the product allowlist + the venv + the updater's scratch/rollback
# dirs. NOT ``.jaeger_os`` (instance state) — that's the operator's, gated
# behind --purge.
_FRAMEWORK = (*_PRODUCT, ".venv", ".update-prev", ".update-staging")
_STATE_DIR = ".jaeger_os"


def _rm(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        path.unlink(missing_ok=True)


def _confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N]: ").strip().lower().startswith("y")


def _cmd_uninstall_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger uninstall", add_help=False)
    parser.add_argument("--purge", action="store_true",
                        help="also wipe .jaeger_os/ (all agents + state)")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger uninstall [--purge] [--yes]\n"
            "\n"
            "  Remove the framework (product files + .venv). Keeps .jaeger_os/\n"
            "  (your agents) unless --purge. Refuses on a dev clone.\n",
            file=sys.stderr,
        )
        return 0

    from jaeger_ai.core.instance.instance import PACKAGE_ROOT
    home = PACKAGE_ROOT.parent
    if (home / ".git").exists():
        print(f"[jaeger uninstall] {home} is a dev clone (.git present) — "
              "uninstall is for deployed installs; remove the clone by hand if "
              "you mean to.", file=sys.stderr)
        return 2

    state = home / _STATE_DIR
    present = [i for i in _FRAMEWORK if (home / i).exists()]
    print(f"[jaeger uninstall] install root: {home}")
    print(f"[jaeger uninstall] framework to remove: "
          f"{', '.join(present) or '(nothing found)'}")
    if args.purge:
        print(f"[jaeger uninstall] --purge: will ALSO wipe {state} "
              "(every agent + all state — irreversible).")
    elif state.exists():
        print(f"[jaeger uninstall] agents at {state} will be KEPT "
              "(re-install over them, or --purge to remove).")

    if not args.yes:
        if not sys.stdin.isatty():
            print("[jaeger uninstall] non-interactive — pass --yes to proceed.",
                  file=sys.stderr)
            return 2
        if args.purge and state.exists():
            print("[jaeger uninstall] tip: `jaeger backup <name>` first to keep "
                  "an agent you might want back.")
            ok = _confirm(f"Remove the framework AND wipe {state} "
                          "(every agent, irreversible)?")
        else:
            ok = _confirm("Remove the framework? (agents kept)")
        if not ok:
            print("[jaeger uninstall] aborted.")
            return 0

    for item in present:
        _rm(home / item)
    if args.purge:
        _rm(state)

    print("[jaeger uninstall] framework removed.")
    if not args.purge and state.exists():
        print(f"[jaeger uninstall] agents kept at {state}.")
    if home.exists() and not any(home.iterdir()):
        print(f"[jaeger uninstall] {home} is now empty — `rmdir {home}` to finish.")
    print("[jaeger uninstall] done.")
    return 0


__all__ = ["_cmd_uninstall_argv"]
