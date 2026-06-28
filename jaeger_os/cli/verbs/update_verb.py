"""``jaeger update`` (INST-7) — upgrade the framework + walk every
instance, prompting per-instance to apply pending migrations.

What this verb actually does:

  1. Detect the install method and run the matching upgrade:
       - dev clone (.git)  → fast-forward git pull + editable reinstall;
       - clean curl install → download the target release tarball and
         swap the product files in place (no git), keeping ``.venv/`` +
         ``.jaeger_os/``. ``--ref`` pins a version; ``--rollback`` reverts.
       - pip / pipx        → the matching upgrade command.
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
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
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


# ── download + apply (clean / product-only install — no .git to pull) ──────
#
# A clean curl install has no ``.git``, so ``git pull`` can't update it.
# Instead we download the target release's tarball and swap the product files
# in place, leaving ``.venv/`` and ``.jaeger_os/`` (the model + every byte of
# instance state) untouched. ``_PRODUCT`` mirrors scripts/install.sh's PRODUCT
# allowlist — keep the two in sync.

_PRODUCT = (
    "jaeger_os",
    "install.sh", "run.sh", "jaeger",
    "requirements.txt", "pyproject.toml",
    "jaeger.toml", "jaeger.windowed.toml",
    "README.md", "LICENSE", "CHANGELOG.md",
)
_PREV_DIR = ".update-prev"        # previous product, kept for --rollback
_STAGING_DIR = ".update-staging"  # new product assembled here before the swap
# General ref form (tag OR branch OR sha) so the `latest` channel can fetch a
# branch (master), not just a release tag.
_ARCHIVE_URL = "https://github.com/{repo}/archive/{ref}.tar.gz"
_LATEST_BRANCH = "master"   # the `latest` channel = development HEAD


def _reinstall_deps(home: Path) -> int:
    """Editable-reinstall into the install's own ``.venv`` (prefer ``uv``,
    fall back to the venv's pip, then the current interpreter) to resync deps
    after the product files change. Returns the process exit code."""
    venv = home / ".venv"
    uv, py = venv / "bin" / "uv", venv / "bin" / "python"
    if uv.exists():
        cmd = [str(uv), "pip", "install", "--python", str(py), "-e", str(home)]
    else:
        base = str(py) if py.exists() else sys.executable
        cmd = [base, "-m", "pip", "install", "-e", str(home)]
    print(f"[jaeger update] resyncing deps: {' '.join(cmd)}")
    return subprocess.run(cmd, check=False).returncode


def _download_tarball(repo: str, ref: str, dest: Path) -> None:
    """Fetch the GitHub tag tarball for ``ref`` to ``dest``."""
    url = _ARCHIVE_URL.format(repo=repo, ref=ref)
    print(f"[jaeger update] downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "jaeger-update"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (https)
        dest.write_bytes(resp.read())


def _extract_product(tarball: Path, staging: Path) -> list[str]:
    """Extract ``tarball`` and copy the PRODUCT items into ``staging``. The
    archive's single top-level dir (``JROS-<ref>``) is detected, not assumed.
    Returns the product items actually present in the archive."""
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tarball) as tf:
            tf.extractall(tmp, filter="data")  # filter: block path traversal
        tops = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(tops) != 1:
            raise RuntimeError(
                f"unexpected archive layout: {[p.name for p in tops]}")
        root = tops[0]
        copied: list[str] = []
        for item in _PRODUCT:
            src = root / item
            if not src.exists():
                continue
            dst = staging / item
            shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
            copied.append(item)
    return copied


def _swap_in(home: Path, staging: Path, items: list[str], prev: Path) -> list[str]:
    """Move current ``items`` aside into ``prev``, then move staged items into
    ``home``. Per-item ``os.replace`` is atomic on one filesystem (staging +
    prev both live under ``home``); a crash mid-swap is recoverable from
    ``prev`` via ``--rollback``. Returns the items swapped."""
    if prev.exists():
        shutil.rmtree(prev)
    prev.mkdir(parents=True)
    swapped: list[str] = []
    for item in items:
        new = staging / item
        if not new.exists():
            continue
        cur = home / item
        if cur.exists():
            os.replace(cur, prev / item)   # stash the old
        os.replace(new, home / item)       # install the new
        swapped.append(item)
    return swapped


def _restore(home: Path, prev: Path, items: list[str]) -> list[str]:
    """Inverse of :func:`_swap_in` — move ``items`` from ``prev`` back into
    ``home``, replacing whatever is there. Returns the items restored."""
    restored: list[str] = []
    for item in items:
        saved = prev / item
        if not saved.exists():
            continue
        cur = home / item
        if cur.exists():
            shutil.rmtree(cur) if cur.is_dir() else cur.unlink()
        os.replace(saved, home / item)
        restored.append(item)
    return restored


def _deps_changed(home: Path, prev: Path) -> bool:
    """True if requirements.txt / pyproject.toml differ between the new
    (``home``) and previous (``prev``) product — gates the dep reinstall."""
    for f in ("requirements.txt", "pyproject.toml"):
        a, b = prev / f, home / f
        if a.exists() != b.exists():
            return True
        if a.exists() and b.exists() and a.read_bytes() != b.read_bytes():
            return True
    return False


def _update_download(home: Path, *, ref: str | None = None,
                     force: bool = False) -> int:
    """Download + apply a release into a clean (no-.git) install. With no
    ``ref``, looks up the latest GitHub tag and no-ops if already current.
    ``force`` (reinstall) re-fetches even the current version and always
    resyncs deps — no up-to-date short-circuit."""
    import jaeger_os
    from jaeger_os.core import version_check

    repo = version_check.repo_slug()
    current = jaeger_os.__version__
    if ref is None:
        if force:
            ref = current                       # reinstall the current version
        else:
            latest = version_check.latest_version(repo)
            if latest is None:
                print("[jaeger update] couldn't reach GitHub to check for updates "
                      "— try again, or pass --ref.", file=sys.stderr)
                return 1
            if not version_check.is_newer(latest, current):
                print(f"[jaeger update] already up to date (v{current}).")
                return 0
            ref = latest
            print(f"[jaeger update] update available: v{current} → {ref}")
    if force:
        print(f"[jaeger update] reinstalling {ref} — clean re-fetch of the product.")

    staging, prev = home / _STAGING_DIR, home / _PREV_DIR
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with tempfile.TemporaryDirectory() as td:
            tarball = Path(td) / "jros.tar.gz"
            _download_tarball(repo, ref, tarball)
            copied = _extract_product(tarball, staging)
        if "jaeger_os" not in copied:
            print("[jaeger update] archive missing jaeger_os/ — aborting "
                  "(nothing changed).", file=sys.stderr)
            return 1
        swapped = _swap_in(home, staging, copied, prev)
        print(f"[jaeger update] applied {len(swapped)} item(s); previous kept "
              f"in {_PREV_DIR}/ (`jaeger update --rollback` to revert).")
        if force or _deps_changed(home, prev):
            rc = _reinstall_deps(home)
            if rc != 0:
                print(f"[jaeger update] dep resync exited {rc} — `jaeger update "
                      f"--rollback` to revert.", file=sys.stderr)
                return rc
        else:
            print("[jaeger update] dependencies unchanged — skipped reinstall.")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    verb = "reinstalled" if force else "now at"
    print(f"[jaeger update] {verb} {ref}. Restart `jaeger` to apply.")
    return 0


def _do_rollback(home: Path) -> int:
    """``jaeger update --rollback`` — restore the product the last
    download-update stashed, then resync deps. One level only (the prev dir is
    consumed)."""
    prev = home / _PREV_DIR
    items = [p.name for p in prev.iterdir()] if prev.exists() else []
    if not items:
        print("[jaeger update] nothing to roll back to "
              "(no previous version kept).", file=sys.stderr)
        return 1
    restored = _restore(home, prev, items)
    print(f"[jaeger update] rolled back {len(restored)} item(s).")
    _reinstall_deps(home)
    shutil.rmtree(prev, ignore_errors=True)
    print("[jaeger update] restart `jaeger` to apply the rolled-back version.")
    return 0


def _update_editable(*, ref: str | None = None) -> int:
    """Editable / clone install (the default since 0.6). With a ``.git`` (dev
    clone) → fast-forward pull + editable reinstall, refusing a dirty tree.
    Without ``.git`` (clean curl/product install) → download + apply the
    release in place."""
    from jaeger_os.core.instance.instance import PACKAGE_ROOT
    repo = PACKAGE_ROOT.parent  # jaeger_os/ -> install root
    if not (repo / ".git").exists():
        return _update_download(repo, ref=ref)
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
    return _reinstall_deps(repo)


def _run_upgrade(method: str, *, ref: str | None = None) -> int:
    if method == "dev-checkout":            # editable / clone install (default 0.6+)
        return _update_editable(ref=ref)
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


def _resolve_ref(ref: str | None, channel: str) -> str | None:
    """The effective ref to install. Precedence: explicit ``--ref`` →
    ``--channel latest`` (master) → ``$JAEGER_REF`` → ``None`` (the ``stable``
    channel: newest release tag, resolved later by the latest-tag lookup)."""
    if ref:
        return ref
    if channel == "latest":
        return _LATEST_BRANCH
    return os.environ.get("JAEGER_REF", "").strip() or None


def _cmd_update_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger update", add_help=False)
    parser.add_argument("--check", action="store_true",
                        help="don't upgrade or migrate — print plan + exit")
    parser.add_argument("--no-migrate", action="store_true",
                        help="run the framework upgrade but skip migration scan")
    parser.add_argument("--ref", default=None,
                        help="exact version/tag/branch to install (overrides --channel)")
    parser.add_argument("--channel", choices=("stable", "latest"), default="stable",
                        help="stable = newest release tag (default); "
                             "latest = development HEAD (master)")
    parser.add_argument("--rollback", action="store_true",
                        help="revert the last download-update (clean installs)")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger update [--check] [--no-migrate] [--channel stable|latest]\n"
            "                     [--ref TAG] [--rollback]\n"
            "\n"
            "  Upgrade the framework via the detected install method, then\n"
            "  prompt to back up and migrate each stale instance.\n"
            "\n"
            "  Clean (curl/product) installs download + apply in place — no git\n"
            "  needed. Channels: stable (newest release tag, default) · latest\n"
            "  (master / development HEAD). --ref pins an exact tag/branch/sha\n"
            "  and overrides --channel; $JAEGER_REF is honoured when neither is\n"
            "  set. --rollback reverts the previous download-update. Dev clones\n"
            "  fast-forward via git.\n",
            file=sys.stderr,
        )
        return 0

    if args.rollback:
        from jaeger_os.core.instance.instance import PACKAGE_ROOT
        return _do_rollback(PACKAGE_ROOT.parent)

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

    rc = _run_upgrade(method, ref=_resolve_ref(args.ref, args.channel))
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


def _cmd_reinstall_argv(argv: list[str]) -> int:
    """``jaeger reinstall`` — clean reinstall of the framework in place,
    keeping every agent (``.jaeger_os/`` is never touched).

      * clean install (no .git) → re-fetch the product (current version, or
        ``--ref``) and force a dep resync — fixes corrupted/half-updated files.
      * dev clone (.git)        → repair the editable install against the
        working tree (no re-fetch).

    For a fully fresh Python env, re-run the installer (``./install.sh``)."""
    parser = argparse.ArgumentParser(prog="jaeger reinstall", add_help=False)
    parser.add_argument("--ref", default=None,
                        help="version/tag to reinstall (default: current)")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger reinstall [--ref TAG]\n"
            "\n"
            "  Clean reinstall of the framework, keeping all agents/state.\n"
            "  Clean install → re-fetch the product + resync deps; dev clone →\n"
            "  repair the editable install. Recovers a broken / half-updated\n"
            "  install. For a fresh Python env, re-run ./install.sh.\n",
            file=sys.stderr,
        )
        return 0

    from jaeger_os.core.instance.instance import PACKAGE_ROOT
    home = PACKAGE_ROOT.parent
    if (home / ".git").exists():
        print(f"[jaeger reinstall] dev clone at {home} — repairing the editable "
              "install (code is your working tree; not re-fetching).")
        rc = _reinstall_deps(home)
        if rc == 0:
            print("[jaeger reinstall] done. Restart `jaeger` to apply.")
        return rc
    return _update_download(home, ref=args.ref, force=True)


__all__ = ["_cmd_update_argv", "_cmd_reinstall_argv"]
