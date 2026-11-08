"""Coordinated product updates and per-instance migration.

Product Git installs pin a fetched revision and retain a recovery ref. Archive
installs swap allowlisted source with a recovery copy. Developer checkouts keep
their fast-forward branch workflow. Environments and operator state stay external.
App/services must be stopped before code replacement; no service is restarted.
Migrations are discovered in a fresh upgraded process and failures propagate.
``--check`` inspects local schemas only; it never checks remote availability.
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

from jaeger_ai.contract.updates import (
    DEFAULT_UPDATE_CHANNEL, UPDATE_CHANNELS, UPDATE_PREVIOUS_GIT_REF, UPDATE_PENDING_GIT_REF,
)


def _detect_method() -> str:
    """Same detection as ``instance.detect_install_method`` —
    re-imported here for clarity at call sites."""
    from jaeger_ai.core.instance.instance import install_root
    if (install_root() / ".jaeger-product-install").is_file():
        return "product-checkout"
    from jaeger_ai.core.instance.instance import detect_install_method
    return detect_install_method()


def _upgrade_command(method: str) -> list[str] | None:
    """Return the argv the wrapper should ``subprocess.run`` for
    this install method, or None when no upgrade can be performed
    automatically."""
    if method == "pipx":
        return ["pipx", "upgrade", "jaeger-ai"]
    if method == "pip":
        return [sys.executable, "-m", "pip", "install", "-U", "jaeger-ai"]
    return None  # dev-checkout / unknown — user-driven


# ── download + apply (clean / product-only install — no .git to pull) ──────
#
# A clean curl install has no ``.git``, so ``git pull`` can't update it.
# Instead we download the target release's tarball and swap the product files
# in place, leaving ``.venv/`` and ``.jaeger_ai/`` (the model + every byte of
# instance state) untouched. ``_PRODUCT`` mirrors scripts/install.sh's PRODUCT
# allowlist — keep the two in sync.

_PRODUCT = (
    "jaeger_ai", "packages", "scripts", "apps", ".gitmodules",
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


def _preflight_update(home: Path) -> int:
    """Refuse to replace code while clients/services can still execute it."""
    import errno
    import socket
    from jaeger_ai.contract.ports import GATEWAY_PORT, WEBUI_PORT, LOOPBACK

    for port in (GATEWAY_PORT, int(os.environ.get("JAEGER_WEBUI_PORT") or WEBUI_PORT)):
        try:
            with socket.create_connection((LOOPBACK, port), timeout=1):
                print(f"[jaeger update] service still listening on {port}. "
                      "Quit Jaeger and stop its services before updating; nothing changed.", file=sys.stderr)
                return 1
        except OSError as exc:
            if exc.errno != errno.ECONNREFUSED:
                print(f"[jaeger update] cannot verify stopped services: {exc}", file=sys.stderr)
                return 1
    if sys.platform == "darwin":
        result = subprocess.run(["pgrep", "-x", "JaegerShell"], capture_output=True, text=True)
        if result.returncode != 1:
            print("[jaeger update] quit the native Jaeger shell before updating "
                  "(or process inspection failed); nothing changed.", file=sys.stderr)
            return 1
    return 0


def _git(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(home), *args],
                          capture_output=True, text=True, check=True)


def _update_product_git(home: Path, *, ref: str | None = None) -> int:
    """Pin a product checkout to a fetched commit, retaining its recovery ref."""
    from jaeger_ai.core import version_check
    if _preflight_update(home):
        return 1
    try:
        if _git(home, "status", "--porcelain").stdout.strip():
            print("[jaeger update] product checkout has uncommitted changes; nothing changed.", file=sys.stderr)
            return 1
        pending = subprocess.run(["git", "-C", str(home), "show-ref", "--verify", "--quiet", UPDATE_PENDING_GIT_REF], check=False)
        if pending.returncode != 1:
            print("[jaeger update] previous installation is incomplete; use --rollback "
                  "before another update. Recovery was retained.", file=sys.stderr)
            return 1
        selected = ref or version_check.latest_release(version_check.repo_slug())
        if not selected or selected.startswith("-"):
            print("[jaeger update] cannot resolve update version; pass --ref or retry.", file=sys.stderr)
            return 1
        # Fetch only the selected ref. FETCH_HEAD is then resolved exactly once;
        # no moving branch is consulted during installation.
        _git(home, "fetch", "--no-tags", "origin", selected)
        commit = _git(home, "rev-parse", "--verify", "FETCH_HEAD^{commit}").stdout.strip()
        previous = _git(home, "rev-parse", "HEAD").stdout.strip()
        if ref is None:
            ancestor = subprocess.run(["git", "-C", str(home), "merge-base", "--is-ancestor", commit, previous], check=False)
            if ancestor.returncode == 0:
                print(f"[jaeger update] installed revision {previous} already contains stable {selected}.")
                return 0
            if ancestor.returncode != 1:
                return ancestor.returncode
        candidate = _git(home, "show", commit + ":jaeger_ai/cli/verbs/update_verb.py").stdout
        if "--finish-update" not in candidate:
            print("[jaeger update] target predates coordinated migration support. "
                  "Use a separate installation for this historical version; nothing changed.", file=sys.stderr)
            return 1
        # Compare-and-create prevents two updaters from replacing one another's
        # recovery point after both passed the read-only preflight.
        _git(home, "update-ref", UPDATE_PENDING_GIT_REF, commit, "")
        _git(home, "update-ref", UPDATE_PREVIOUS_GIT_REF, previous)
        _git(home, "checkout", "--detach", commit)
        print(f"[jaeger update] selected {selected} → {commit}; previous revision retained for --rollback.")
        rc = _reinstall_deps(home)
        if not rc:
            rc = _rebuild_mac_shell(home, only_if_stale=True)
        if rc:
            print("[jaeger update] installation incomplete; keep services stopped. "
                  "Run jaeger update --rollback to restore the previous revision.", file=sys.stderr)
        else:
            _git(home, "update-ref", "-d", UPDATE_PENDING_GIT_REF)
        return rc or 0
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[jaeger update] product update failed: {exc}; keep services stopped. "
              "A retained previous revision can be restored with --rollback.", file=sys.stderr)
        return 1


def _reinstall_deps(home: Path) -> int:
    """Refresh all coordinated wheels in the active external environment."""
    venv = Path(os.environ.get("JAEGER_VENV") or sys.prefix).expanduser()
    py = venv / "bin" / "python"
    cmd = [str(py), str(home / "scripts/install-packages.py"), "--python", str(py)]
    cmd.extend(str(home / "packages" / name) + extra for name, extra in (
        ("jaeger-os", ""), ("jaeger-agent", "[multimodal-duplex]"),
        ("jaeger-kokoro-tts", ""), ("jaeger-whisper-stt", ""),
    ))
    cmd.append(str(home))
    print(f"[jaeger update] refreshing installed packages from {home}")
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
    archive's single top-level dir (``JaegerAI-<ref>``) is detected, not assumed.
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
        # Keep the recovery source intact until dependency and app restoration
        # have succeeded. A failed reinstall must be safely retryable.
        shutil.copytree(saved, home / item) if saved.is_dir() else shutil.copy2(saved, home / item)
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
    import jaeger_ai
    from jaeger_ai.core import version_check

    repo = version_check.repo_slug()
    current = jaeger_ai.__version__
    if ref is None:
        if force:
            ref = current                       # reinstall the current version
        else:
            latest = version_check.latest_release(repo)
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

    if _preflight_update(home):
        return 1
    staging, prev = home / _STAGING_DIR, home / _PREV_DIR
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with tempfile.TemporaryDirectory() as td:
            tarball = Path(td) / "jaeger.tar.gz"
            _download_tarball(repo, ref, tarball)
            copied = _extract_product(tarball, staging)
        if "jaeger_ai" not in copied:
            print("[jaeger update] archive missing jaeger_ai/ — aborting "
                  "(nothing changed).", file=sys.stderr)
            return 1
        swapped = _swap_in(home, staging, copied, prev)
        print(f"[jaeger update] applied {len(swapped)} item(s); previous kept "
              f"in {_PREV_DIR}/ (`jaeger update --rollback` to revert).")
        # Code can change without a requirements/version change. Installed
        # wheels and the shared UI must always follow the swapped source.
        if swapped:
            rc = _reinstall_deps(home)
            if rc != 0:
                print(f"[jaeger update] dep resync exited {rc} — `jaeger update "
                      f"--rollback` to revert.", file=sys.stderr)
                return rc
        else:
            print("[jaeger update] dependencies unchanged — skipped reinstall.")
        rc = _rebuild_mac_shell(home)
        if rc:
            return rc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    verb = "reinstalled" if force else "now at"
    print(f"[jaeger update] {verb} {ref}. Restart `jaeger` to apply.")
    return 0


def _rebuild_mac_shell(home: Path, *, only_if_stale: bool = False) -> int:
    """Build the canonical shared-UI shell without installing or starting it."""
    from jaeger_ai.cli._common import mac_app_bundle, mac_app_is_stale
    script = home / "jaeger_ai/interfaces/macos-shell/Scripts/build-shell.sh"
    if not script.is_file():
        return 0
    try:
        bundle = mac_app_bundle(home)
        if only_if_stale and not mac_app_is_stale(home, bundle):
            return 0
    except ValueError as exc:
        print(f"[jaeger update] Mac build configuration invalid: {exc}", file=sys.stderr)
        return 1
    if sys.platform != "darwin":
        return 0
    if shutil.which("swift") is None:
        print("[jaeger update] Swift unavailable; canonical Mac shell was not built", file=sys.stderr)
        return 1
    result = subprocess.run(["bash", str(script)], stdout=subprocess.DEVNULL)
    print(f"[jaeger update] canonical Mac shell build exited {result.returncode}")
    return result.returncode


def jaeger_exe() -> Path:
    """The source-bound wrapper, falling back to the active external console. Shared by the
    CLI and the app-bridge ``run_update`` command below, so both spawn the SAME
    executable a hand-typed ``jaeger update`` would run."""
    from jaeger_ai.core.instance.instance import install_root
    home = install_root()
    wrapper = home / "jaeger"
    if wrapper.is_file():
        return wrapper
    venv = Path(os.environ.get("JAEGER_VENV") or sys.prefix) / "bin/jaeger"
    return venv if venv.is_file() else wrapper


def run_update_subprocess(*, ref: str | None = None,
                          timeout: float = 600.0) -> dict[str, Any]:
    """Run ``jaeger update [--ref REF]`` as a subprocess and report the
    outcome — the app-bridge's ``run_update`` command calls this so the
    native app never reimplements the upgrade logic, just triggers the
    SAME machinery ``jaeger update`` runs (dev-clone pull vs. tarball
    swap, picked internally by install-method detection in
    :func:`_cmd_update_argv`).

    The child's stdin is closed (``DEVNULL``): ``_ask_yn`` (the
    per-stale-instance migration prompt) already takes its default
    (yes) when ``stdin`` isn't a tty, so this runs exactly as
    non-interactively as ``jaeger update < /dev/null`` would.

    Returns ``{ok, returncode, output, restart_required, error}``.
    ``restart_required`` is True whenever the subprocess actually ran
    (0 or nonzero exit — even a partial/failed apply may have changed
    files that need a restart to either take effect or be inspected);
    it's False only when the subprocess couldn't be launched at all.
    """
    argv = [str(jaeger_exe()), "update"]
    if ref:
        argv += ["--ref", ref]
    try:
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "returncode": None,
                "output": exc.stdout or "", "restart_required": True,
                "error": f"update timed out after {timeout:.0f}s"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "returncode": None, "output": "",
                "restart_required": False, "error": str(exc)}
    ok = result.returncode == 0
    return {"ok": ok, "returncode": result.returncode,
            "output": result.stdout or "", "restart_required": True,
            "error": None if ok else f"update exited {result.returncode}"}


def _do_rollback(home: Path) -> int:
    """``jaeger update --rollback`` — restore the product the last
    download-update stashed, then resync deps. One level only (the prev dir is
    consumed)."""
    if _preflight_update(home):
        return 1
    if (home / ".git").exists():
        try:
            if _git(home, "status", "--porcelain").stdout.strip():
                print("[jaeger update] working tree is dirty; rollback refused.", file=sys.stderr)
                return 1
            commit = _git(home, "rev-parse", "--verify", UPDATE_PREVIOUS_GIT_REF + "^{commit}").stdout.strip()
            _git(home, "checkout", "--detach", commit)
            rc = _reinstall_deps(home)
            if not rc:
                rc = _rebuild_mac_shell(home)
            if rc:
                print("[jaeger update] rollback incomplete; recovery ref retained. Retry --rollback.", file=sys.stderr)
                return rc
            _git(home, "update-ref", "-d", UPDATE_PREVIOUS_GIT_REF)
            _git(home, "update-ref", "-d", UPDATE_PENDING_GIT_REF)
            return 0
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"[jaeger update] Git rollback failed: {exc}", file=sys.stderr)
            return 1
    prev = home / _PREV_DIR
    items = [p.name for p in prev.iterdir()] if prev.exists() else []
    if not items:
        print("[jaeger update] nothing to roll back to "
              "(no previous version kept).", file=sys.stderr)
        return 1
    restored = _restore(home, prev, items)
    print(f"[jaeger update] rolled back {len(restored)} item(s).")
    rc = _reinstall_deps(home)
    if rc:
        print(f"[jaeger update] rollback dependency restoration failed ({rc}); "
              f"recovery copy retained at {prev}. Retry --rollback.", file=sys.stderr)
        return rc
    rc = _rebuild_mac_shell(home)   # the built app must match the restored core
    if rc:
        print(f"[jaeger update] rollback app build failed ({rc}); recovery copy retained.", file=sys.stderr)
        return rc
    shutil.rmtree(prev, ignore_errors=True)
    print("[jaeger update] restart `jaeger` to apply the rolled-back version.")
    return 0


def _update_editable(*, ref: str | None = None) -> int:
    """Editable / clone install (the default since 0.6). With a ``.git`` (dev
    clone) → fast-forward pull + editable reinstall, refusing a dirty tree.
    Without ``.git`` (clean curl/product install) → download + apply the
    release in place."""
    from jaeger_ai.core.instance.instance import install_root
    repo = install_root()  # jaeger_ai/ -> install root
    if not (repo / ".git").exists():
        return _update_download(repo, ref=ref)
    if _preflight_update(repo):
        return 1
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                           capture_output=True, text=True)
    if dirty.stdout.strip():
        print("[jaeger update] working tree has uncommitted changes — pull yourself:")
        print(f"                 cd {repo} && git pull --ff-only && ./install.sh")
        return 1
    if ref is not None and ref != _LATEST_BRANCH:
        print("[jaeger update] pinned refs require a product install; select the "
              "desired ref explicitly in your developer checkout.", file=sys.stderr)
        return 1
    print(f"[jaeger update] pulling latest in {repo}…")
    pull = subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"], check=False)
    if pull.returncode != 0:
        print("[jaeger update] git pull --ff-only failed (diverged?) — resolve manually.",
              file=sys.stderr)
        return pull.returncode
    rc = _reinstall_deps(repo)
    # The .app is a build artifact the pull can't deliver — rebuild whenever
    # the Swift tree moved past the built bundle's stamp (also catches pulls
    # done by hand and installs whose first build failed → missing app).
    if rc:
        return rc
    return _rebuild_mac_shell(repo, only_if_stale=True) or 0


def _run_upgrade(method: str, *, ref: str | None = None) -> int:
    if method == "product-checkout":
        from jaeger_ai.core.instance.instance import install_root
        home = install_root()
        return _update_product_git(home, ref=ref) if (home / ".git").exists() else _update_download(home, ref=ref)
    if method == "dev-checkout":
        return _update_editable(ref=ref)
    cmd = _upgrade_command(method)
    if cmd is None:
        print("[jaeger update] unknown install method — upgrade manually.")
        return 1
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
    from jaeger_ai.core.instance.instance import user_instances_root
    from jaeger_ai.core.instance.schemas import SCHEMA_VERSION

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
    from jaeger_ai.cli.verbs.backup_restore import backup_instance
    from jaeger_ai.core.instance.instance import (
        InstanceLayout, resolve_instance_dir,
    )
    from jaeger_ai.core.instance.migrations import run_pending_migrations

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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--finish-update", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--check", action="store_true",
                        help="don't upgrade or migrate — print plan + exit")
    parser.add_argument("--no-migrate", action="store_true",
                        help="run the framework upgrade but skip migration scan")
    parser.add_argument("--ref", default=None,
                        help="exact version/tag/branch to install (overrides --channel)")
    parser.add_argument("--channel", choices=UPDATE_CHANNELS, default=DEFAULT_UPDATE_CHANNEL,
                        help="stable = newest release tag (default); "
                             "latest = development HEAD (master)")
    mode.add_argument("--rollback", action="store_true",
                        help="restore the previous product revision and rebuild installed packages")
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
            "  Quit the app and stop Gateway/WebUI services before updating.\n"
            "  Product Git installs pin a fetched commit; archive installs swap source.\n"
            "  Channels: stable (published stable release, default) · latest\n"
            "  (master / development HEAD). --ref pins an exact tag/branch/sha\n"
            "  and overrides --channel; $JAEGER_REF is honoured when neither is\n"
            "  set. --rollback restores the previous product code. Dev clones\n"
            "  fast-forward via git.\n",
            file=sys.stderr,
        )
        return 0

    if args.finish_update:
        return _finish_update(no_migrate=args.no_migrate)

    if args.rollback:
        from jaeger_ai.core.instance.instance import install_root
        return _do_rollback(install_root())

    method = _detect_method()
    # ``dev-checkout`` is the detector's name for ANY source-tree run,
    # but a clean curl install has no .git and updates by tarball —
    # label it honestly so operators don't think they're on a git clone.
    label = method
    if method in ("dev-checkout", "product-checkout"):
        from jaeger_ai.core.instance.instance import install_root
        if method == "product-checkout":
            label = "Jaeger AI product install"
        elif not (install_root() / ".git").exists():
            label = "clean install (download + apply)"
    print(f"[jaeger update] install method: {label}")

    if args.check:
        return _finish_update(check=True)

    from jaeger_ai.core.instance.instance import install_root
    if _preflight_update(install_root()):
        return 1
    rc = _run_upgrade(method, ref=_resolve_ref(args.ref, args.channel))
    if rc != 0:
        return rc
    return _finish_update_subprocess(no_migrate=args.no_migrate)


def _finish_update_subprocess(*, no_migrate: bool = False) -> int:
    """Load migration discovery and execution from the newly installed core."""
    argv = [str(jaeger_exe()), "update", "--finish-update"]
    if no_migrate:
        argv.append("--no-migrate")
    result = subprocess.run(argv, check=False)
    if result.returncode:
        print("[jaeger update] post-install checks failed; keep services stopped. "
              "Inspect the error and use --rollback if needed.", file=sys.stderr)
    return result.returncode


def _finish_update(*, no_migrate: bool = False, check: bool = False) -> int:
    stale = [] if no_migrate else _list_stale_instances()
    if stale:
        print(f"[jaeger update] {len(stale)} instance(s) need migration:")
        for entry in stale:
            print(f"  - {entry['name']} (current: {entry['current_version']})")
    else:
        print("[jaeger update] no migration needed for the installed core.")
    if check:
        print("[jaeger update] local schema check only; remote updates were not checked.")
        return 1 if stale else 0
    failed = 0
    for entry in stale:
        name = entry["name"]
        if not _ask_yn(f"  back up + migrate {name!r}?", True):
            print(f"[jaeger update] {name!r}: migration deferred.")
            failed = failed or 1
            continue
        rc = _migrate_instance_with_backup(name)
        failed = failed or rc
    if failed:
        print("[jaeger update] migrations incomplete; update is not complete. "
              "Keep services stopped and retry the migration or restore a backup.", file=sys.stderr)
        return failed
    print("[jaeger update] Restart `jaeger` to apply, then verify the running "
          "Gateway and native app revisions. No services were restarted.")
    return 0


def _cmd_reinstall_argv(argv: list[str]) -> int:
    """``jaeger reinstall`` — clean reinstall of the framework in place,
    keeping every agent (``.jaeger_ai/`` is never touched).

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

    from jaeger_ai.core.instance.instance import install_root
    home = install_root()
    if args.ref and (home / ".git").exists():
        if (home / ".jaeger-product-install").is_file():
            return _cmd_update_argv(["--ref", args.ref])
        print("[jaeger reinstall] select the desired ref explicitly in your developer checkout.", file=sys.stderr)
        return 1
    if _preflight_update(home):
        return 1
    if (home / ".git").exists():
        print(f"[jaeger reinstall] dev clone at {home} — repairing the editable "
              "install (code is your working tree; not re-fetching).")
        rc = _reinstall_deps(home)
        if rc == 0:
            print("[jaeger reinstall] done. Restart `jaeger` to apply.")
        if rc == 0:
            rc = _rebuild_mac_shell(home, only_if_stale=True)
        return rc
    return _update_download(home, ref=args.ref, force=True)


__all__ = ["_cmd_update_argv", "_cmd_reinstall_argv",
           "jaeger_exe", "run_update_subprocess"]
