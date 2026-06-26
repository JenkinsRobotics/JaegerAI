"""``jaeger update`` (INST-7) — upgrade the framework + walk every
instance, prompting per-instance to apply pending migrations.

What this verb actually does:

  1. Detect the install method (pipx / pip / dev-checkout / unknown)
     and run the matching upgrade command. Editable installs print
     a hint instead — the user controls their git pull.
  2. Print "Restart `jaeger` to apply" — we don't auto-restart a
     running daemon. The user picks when to take the agent down.
  3. Scan ``~/.jaeger/instances/<name>/`` for stale manifests and
     interactively prompt to back up + migrate each one. Skipped on
     ``--no-migrate``; just listed on ``--check``.

``--check`` runs neither the upgrade nor the migration; it prints
what WOULD happen and exits 0 / 1 based on staleness.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _detect_method() -> str:
    """Same detection as ``instance.detect_install_method`` —
    re-imported here for clarity at call sites."""
    from jaeger_os.core.instance.instance import detect_install_method
    return detect_install_method()


def _upgrade_command(method: str) -> list[str] | None:
    """Return the argv the wrapper should ``subprocess.run`` for
    this install method, or None when no upgrade can be performed
    automatically."""
    if method == "pipx":
        return ["pipx", "upgrade", "jaeger-os"]
    if method == "pip":
        return [sys.executable, "-m", "pip", "install", "-U", "jaeger-os"]
    return None  # dev-checkout / unknown — user-driven


def _update_editable() -> int:
    """Editable / clone install (the default since 0.6): fast-forward pull
    then resync deps via an editable reinstall — so ``jaeger update`` actually
    updates instead of just printing a hint. Refuses to pull over a dirty tree
    (we never touch a working clone with uncommitted changes)."""
    from jaeger_os.core.instance.instance import PACKAGE_ROOT
    repo = PACKAGE_ROOT.parent  # jaeger_os/ -> repo root
    if not (repo / ".git").exists():
        print("[jaeger update] no .git here — reinstall from source to update.")
        return 0
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                           capture_output=True, text=True)
    if dirty.stdout.strip():
        print("[jaeger update] working tree has uncommitted changes — pull yourself:")
        print(f"                 cd {repo} && git pull --ff-only && uv pip install -e .")
        return 0
    print(f"[jaeger update] pulling latest in {repo}…")
    pull = subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"], check=False)
    if pull.returncode != 0:
        print("[jaeger update] git pull --ff-only failed (diverged?) — resolve manually.",
              file=sys.stderr)
        return pull.returncode
    venv = repo / ".venv"
    uv, py = venv / "bin" / "uv", venv / "bin" / "python"
    if uv.exists():
        cmd = [str(uv), "pip", "install", "--python", str(py), "-e", str(repo)]
    else:
        base = str(py) if py.exists() else sys.executable
        cmd = [base, "-m", "pip", "install", "-e", str(repo)]
    print(f"[jaeger update] resyncing deps: {' '.join(cmd)}")
    res = subprocess.run(cmd, check=False)
    if res.returncode != 0:
        print(f"[jaeger update] reinstall exited {res.returncode}", file=sys.stderr)
        return res.returncode
    return 0


def _run_upgrade(method: str) -> int:
    if method == "dev-checkout":            # editable / clone install (default 0.6+)
        return _update_editable()
    cmd = _upgrade_command(method)
    if cmd is None:
        print("[jaeger update] unknown install method — upgrade manually.")
        return 0
    print(f"[jaeger update] running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=False)
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        print(f"[jaeger update] upgrade failed: {exc}", file=sys.stderr)
        return 2
    if result.returncode != 0:
        print(f"[jaeger update] upgrade exited {result.returncode}",
              file=sys.stderr)
        return result.returncode
    return 0


def _list_stale_instances() -> list[dict[str, Any]]:
    """Walk ``~/.jaeger/instances/`` for instances whose
    ``manifest.json:schema_version`` is not the installed
    ``SCHEMA_VERSION``. Each entry: ``{name, path, current_version}``.
    """
    from jaeger_os.core.instance.instance import user_instances_root
    from jaeger_os.core.instance.schemas import SCHEMA_VERSION

    root = user_instances_root()
    if not root.exists():
        return []
    stale: list[dict[str, Any]] = []
    for inst_dir in sorted(root.iterdir()):
        if not inst_dir.is_dir():
            continue
        mf = inst_dir / "manifest.json"
        if not mf.exists():
            continue
        try:
            current = json.loads(mf.read_text(encoding="utf-8")).get("schema_version")
        except (OSError, json.JSONDecodeError):
            continue
        if current and current != SCHEMA_VERSION:
            stale.append({
                "name": inst_dir.name,
                "path": inst_dir,
                "current_version": current,
            })
    return stale


def _migrate_instance_with_backup(name: str) -> int:
    """Back up + migrate one instance. Returns 0 on success, 2 on
    failure (caller continues to the next instance)."""
    from jaeger_os.cli.verbs.backup_restore import backup_instance
    from jaeger_os.core.instance.instance import (
        InstanceLayout, resolve_instance_dir,
    )
    from jaeger_os.core.instance.migrations import run_pending_migrations

    try:
        archive = backup_instance(name)
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger update]   {name!r}: backup failed: {exc}",
              file=sys.stderr)
        return 2
    print(f"[jaeger update]   {name!r}: backed up → {archive}")

    layout = InstanceLayout(root=resolve_instance_dir(name))
    try:
        applied = run_pending_migrations(layout)
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger update]   {name!r}: migration failed: {exc}",
              file=sys.stderr)
        return 2
    print(f"[jaeger update]   {name!r}: applied {len(applied)} migration(s)")
    for n in applied:
        print(f"[jaeger update]     ✓ {n}")
    return 0


def _ask_yn(prompt: str, default: bool) -> bool:
    """Tiny y/n prompt — used per-stale-instance."""
    if not sys.stdin.isatty():
        # Non-interactive: take the default.
        return default
    hint = "Y/n" if default else "y/N"
    raw = input(f"  {prompt} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw[0] == "y"


def _cmd_update_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger update", add_help=False)
    parser.add_argument("--check", action="store_true",
                        help="don't upgrade or migrate — print plan + exit")
    parser.add_argument("--no-migrate", action="store_true",
                        help="run the framework upgrade but skip migration scan")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger update [--check] [--no-migrate]\n"
            "\n"
            "  Upgrade the framework via the detected install method\n"
            "  (pipx / pip / dev-checkout), then prompt to back up\n"
            "  and migrate each stale instance.\n",
            file=sys.stderr,
        )
        return 0

    method = _detect_method()
    print(f"[jaeger update] install method: {method}")

    stale = _list_stale_instances()
    if stale:
        print(f"[jaeger update] {len(stale)} instance(s) need migration "
              f"after upgrade:")
        for entry in stale:
            print(f"  - {entry['name']} (current: {entry['current_version']})")
    else:
        print("[jaeger update] all instances are at the installed core "
              "version — no migration needed post-upgrade.")

    if args.check:
        return 0 if not stale else 1

    rc = _run_upgrade(method)
    if rc != 0:
        return rc

    if not args.no_migrate and stale:
        print()
        print("[jaeger update] migrating instances…")
        for entry in stale:
            name = entry["name"]
            print()
            print(f"[jaeger update] {name!r}: {entry['current_version']} "
                  f"→ installed core")
            if not _ask_yn(f"  back up + migrate {name!r}?", True):
                print(f"[jaeger update]   {name!r}: skipped.")
                continue
            _migrate_instance_with_backup(name)

    print()
    print("[jaeger update] Restart `jaeger` to apply the new framework "
          "(stop any running daemon with `jaeger stop` first).")
    return 0


__all__ = ["_cmd_update_argv"]
