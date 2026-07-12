"""``jaeger backup`` + ``jaeger restore`` (INST-5, INST-6).

Backup zips an instance's workspace minus regenerable + secret
content, plus a ``MANIFEST.json`` header so restore can validate.

Restore unzips into ``~/.jaeger/instances/<name>/``, refusing on
name collision unless ``--force`` (which renames the existing one
aside with the wizard's ``.bak.<ts>`` pattern).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── exclusion rules ────────────────────────────────────────────────


# Glob patterns matched against paths RELATIVE to the instance root.
# Anything matching is excluded from a default backup. NB: this list
# does NOT include credentials/* or skills/* — those are gated by
# the explicit ``include_credentials`` / ``include_skills`` flags
# and handled BEFORE this list is consulted.
_DEFAULT_EXCLUDES: tuple[str, ...] = (
    "run/*",                        # PID, socket, runtime log
    ".lock",
    ".lock.*",
    "memory/*.embeddings.npz",     # large; regenerable from episodic.jsonl
    "memory/.facts.lock",
    "memory/.schedules.lock",
    "logs/audit.log.[0-9]*",        # rotated logs; keep the live one
    "logs/tool_results/*",          # large spills; the prompt has previews
    # Per-instance subprocess cache piles — caches are regenerable.
    "home/.cache/*",
    "home/.npm/_cacache/*",
)

# What MUST be included even if a generic exclude would catch it.
# Lets us drop credentials/ via the default but keep ``credentials/.gitkeep``
# so restore lands a structurally complete instance.
_FORCED_INCLUDES: tuple[str, ...] = (
    "credentials/.gitkeep",
    "memory/.gitkeep",
    "logs/.gitkeep",
    "skills/.gitkeep",
)


def _should_exclude(rel: str, *, include_credentials: bool,
                    include_skills: bool) -> bool:
    """Return True when ``rel`` (a forward-slash relative path under
    the instance root) should be left out of the backup.

    Order matters:
      1. Forced includes (``.gitkeep`` placeholders) always survive.
      2. credentials/ — included iff ``include_credentials`` else
         excluded outright (overrides any pattern-match below).
      3. skills/ — included iff ``include_skills`` else excluded.
      4. Generic default-exclude patterns (run/, embeddings.npz,
         rotated logs, caches).
    """
    if any(fnmatch.fnmatch(rel, pat) for pat in _FORCED_INCLUDES):
        return False
    if rel.startswith("credentials/"):
        return not include_credentials
    if rel.startswith("skills/"):
        return not include_skills
    return any(fnmatch.fnmatch(rel, pat) for pat in _DEFAULT_EXCLUDES)


# ── backup writer ──────────────────────────────────────────────────


def _backup_manifest(name: str, *,
                     include_credentials: bool,
                     include_skills: bool,
                     files: list[str]) -> dict[str, Any]:
    from jaeger_ai import __version__ as jver
    from jaeger_ai.core.instance.schemas import SCHEMA_VERSION
    return {
        "schema": "jaeger-backup",
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "created_with_framework": jver,
        "schema_version": SCHEMA_VERSION,
        "instance_name": name,
        "include_credentials": include_credentials,
        "include_skills": include_skills,
        "file_count": len(files),
    }


def _backups_dir() -> Path:
    """0.2.6: backups land in ``<install_root>/.jaeger_os/backups/``
    alongside instances/, not the legacy ``~/.jaeger/backups/``."""
    from jaeger_ai.core.instance.instance import operator_state_root
    return operator_state_root() / "backups"


def _default_output_path(name: str) -> Path:
    backups = _backups_dir()
    backups.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return backups / f"{name}-{ts}.zip"


def backup_instance(name: str, *,
                    output: Path | None = None,
                    include_credentials: bool = False,
                    include_skills: bool = True) -> Path:
    """Zip the named instance's workspace minus excluded paths.
    Returns the archive path on success; raises on missing instance
    or write failure."""
    from jaeger_ai.core.instance.instance import (
        InstanceLayout, resolve_instance_dir,
    )
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.root.exists():
        raise FileNotFoundError(
            f"instance {name!r} not found at {layout.root}"
        )

    out_path = output or _default_output_path(name)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    included: list[str] = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(layout.root.rglob("*")):
            if not (path.is_file() or path.is_symlink()):
                continue
            rel_path = path.relative_to(layout.root)
            rel_str = rel_path.as_posix()
            if _should_exclude(rel_str,
                               include_credentials=include_credentials,
                               include_skills=include_skills):
                continue
            try:
                zf.write(path, arcname=f"{name}/{rel_str}")
                included.append(rel_str)
            except OSError:
                # Skip files we can't read (locked sockets etc.).
                continue

        # The manifest goes last so we know the exact file list.
        manifest = _backup_manifest(
            name,
            include_credentials=include_credentials,
            include_skills=include_skills,
            files=included,
        )
        zf.writestr("MANIFEST.json",
                    json.dumps(manifest, indent=2, default=str))

    return out_path


# ── restore reader ─────────────────────────────────────────────────


class RestoreError(RuntimeError):
    """Raised by ``restore_instance`` on a recoverable refusal
    (name conflict, archive too new, etc.). The CLI surfaces the
    message and exits non-zero."""


def _read_backup_manifest(archive: Path) -> dict[str, Any]:
    """Pull MANIFEST.json out of the zip and parse it. Returns an
    empty dict if missing — restore still works against archives
    without a manifest, just with reduced validation."""
    try:
        with zipfile.ZipFile(archive) as zf:
            try:
                body = zf.read("MANIFEST.json").decode("utf-8")
                return json.loads(body)
            except KeyError:
                return {}
    except (zipfile.BadZipFile, OSError) as exc:
        raise RestoreError(f"could not read archive: {exc}") from exc


def restore_instance(archive: Path, *,
                     name_override: str | None = None,
                     force: bool = False) -> Path:
    """Unzip ``archive`` into ``~/.jaeger/instances/<name>/``.

    The archive layout is ``<name>/<file>``; ``name_override`` lets
    the caller restore into a differently-named slot. ``force=True``
    backs up any existing dir at the target before unpacking.

    Returns the path the instance landed at.
    """
    if not archive.exists():
        raise RestoreError(f"archive does not exist: {archive}")

    manifest = _read_backup_manifest(archive)
    # Future-archive guard: refuse to restore something a newer
    # framework wrote — we don't ship downgrade migrations.
    archive_core = manifest.get("schema_version")
    from jaeger_ai.core.instance.schemas import SCHEMA_VERSION
    if archive_core and _ver_gt(archive_core, SCHEMA_VERSION):
        raise RestoreError(
            f"archive was created by a newer framework "
            f"(core {archive_core!r} > installed {SCHEMA_VERSION!r}). "
            "Upgrade jaeger-os before restoring."
        )

    name = name_override or manifest.get("instance_name") or _name_from_archive(archive)
    if not name:
        raise RestoreError(
            "couldn't determine instance name — pass --name NEW"
        )

    from jaeger_ai.core.instance.instance import (
        InstanceLayout, resolve_instance_dir,
    )
    target = resolve_instance_dir(name)
    target = Path(target)

    if target.exists():
        if not force:
            raise RestoreError(
                f"instance {name!r} already exists at {target}. "
                f"Pass --force to back it up + replace, or --name NEW "
                f"to restore alongside."
            )
        # Wizard pattern: rename aside with timestamp.
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        aside = target.with_name(f"{target.name}.bak.{ts}")
        shutil.move(str(target), str(aside))
        print(f"[restore] backed up existing instance to {aside}",
              flush=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()

    # Discover the source prefix inside the archive. With a manifest
    # we trust ``instance_name``; without, we sniff the common
    # top-level dir.
    src_prefix = manifest.get("instance_name") or _archive_top_dir(archive)

    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if info.filename == "MANIFEST.json":
                continue
            # Strip the archive's source prefix so files land at
            # ``target/<rel>`` regardless of what the source was named.
            if src_prefix and info.filename.startswith(src_prefix + "/"):
                rel = info.filename[len(src_prefix) + 1:]
            else:
                rel = info.filename
            if not rel:
                continue
            # Defensive: refuse path-escape attempts in the archive
            # (zip slip — malicious tarball CVE class).
            if rel.startswith("/") or ".." in Path(rel).parts:
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as fh, open(dest, "wb") as out:
                out.write(fh.read())

    # Stamp distribution.yaml so future inspect / update calls know
    # this instance was restored, not created fresh.
    _stamp_restore_provenance(target, archive)

    return target


def _stamp_restore_provenance(target: Path, archive: Path) -> None:
    """Write / update ``distribution.yaml`` to record the restore.

    Preserves ``created_with_framework`` / ``created_at`` if the
    archive carried them; sets ``install_method = imported`` and
    ``restored_from = <archive>``. Best-effort — silent on failure
    so a botched stamp doesn't ruin an otherwise-clean restore.
    """
    try:
        from jaeger_ai.core.instance.schemas import (
            DistributionConfig, dump_yaml, load_yaml,
        )
        from jaeger_ai import __version__ as jver

        dist_path = target / "distribution.yaml"
        if dist_path.exists():
            try:
                existing = load_yaml(dist_path, DistributionConfig)
                dist = existing.model_copy(update={
                    "install_method": "imported",
                    "last_updated_with_framework": jver,
                    "restored_from": str(archive),
                })
            except Exception:  # noqa: BLE001
                dist = DistributionConfig(
                    created_with_framework=jver,
                    last_updated_with_framework=jver,
                    install_method="imported",
                    restored_from=str(archive),
                )
        else:
            dist = DistributionConfig(
                created_with_framework=jver,
                last_updated_with_framework=jver,
                install_method="imported",
                restored_from=str(archive),
            )
        dump_yaml(dist_path, dist)
    except Exception:  # noqa: BLE001 — provenance is advisory
        pass


def _name_from_archive(archive: Path) -> str | None:
    """Fall-back when the archive has no manifest: peek inside for
    the common top-level dir."""
    return _archive_top_dir(archive)


def _archive_top_dir(archive: Path) -> str | None:
    try:
        with zipfile.ZipFile(archive) as zf:
            names = [n for n in zf.namelist() if n != "MANIFEST.json"]
    except (zipfile.BadZipFile, OSError):
        return None
    if not names:
        return None
    candidates = {n.split("/", 1)[0] for n in names if "/" in n}
    if len(candidates) == 1:
        return candidates.pop()
    return None


def _ver_gt(a: str, b: str) -> bool:
    """Tuple-compare ``"1.2.3"`` versions; tags / prereleases stay
    out of scope."""
    def t(s: str) -> tuple[int, ...]:
        return tuple(int(p) for p in s.split(".") if p.isdigit())
    return t(a) > t(b)


# ── CLI plumbing ───────────────────────────────────────────────────


def _pick_backup_interactively() -> Path | None:
    """List zips under ``<install_root>/.jaeger_os/backups/`` (newest
    first) and let the user pick one. Returns ``None`` if the dir is
    empty or stdin isn't a TTY."""
    backups_dir = _backups_dir()
    if not backups_dir.exists():
        print(f"[jaeger restore] no backup dir at {backups_dir}.",
              file=sys.stderr)
        return None
    zips = sorted(backups_dir.glob("*.zip"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        print(f"[jaeger restore] no .zip files in {backups_dir}.",
              file=sys.stderr)
        return None
    if not sys.stdin.isatty():
        print("[jaeger restore] specify the archive explicitly "
              "(stdin is not a tty).", file=sys.stderr)
        return None
    print(f"Backups in {backups_dir}:")
    for i, p in enumerate(zips[:20]):  # cap so we don't drown the user
        size_kb = p.stat().st_size // 1024
        print(f"     {i + 1}. {p.name}   ({size_kb:,} KB)")
    if len(zips) > 20:
        print(f"     … and {len(zips) - 20} more — pass the path explicitly.")
    while True:
        raw = input(f"  Pick 1-{min(len(zips), 20)}: ").strip()
        if not raw:
            return None
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= min(len(zips), 20):
                return zips[idx - 1]
        print(f"     (pick 1-{min(len(zips), 20)} or ^C to abort)")


def _cmd_backup_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger backup", add_help=False)
    parser.add_argument("--name", default=None,
                        help="instance name (default: active)")
    parser.add_argument("--output", default=None,
                        help="archive path (default: ~/.jaeger/backups/<name>-<ts>.zip)")
    parser.add_argument("--include-credentials", action="store_true",
                        help="include credentials/ in the archive (DEFAULT EXCLUDED)")
    parser.add_argument("--no-skills", dest="include_skills",
                        action="store_false", default=True,
                        help="exclude user-authored skills/ from the archive")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger backup [--name NAME] [--output PATH]\n"
            "                     [--include-credentials] [--no-skills]\n",
            file=sys.stderr,
        )
        return 0

    from jaeger_ai.core.instance.instance import default_instance_name
    name = args.name or default_instance_name()
    output = Path(args.output).expanduser() if args.output else None

    try:
        archive = backup_instance(
            name,
            output=output,
            include_credentials=args.include_credentials,
            include_skills=args.include_skills,
        )
    except FileNotFoundError as exc:
        print(f"[jaeger backup] {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"[jaeger backup] write failed: {exc}", file=sys.stderr)
        return 2

    size = archive.stat().st_size
    print(f"[jaeger backup] {name!r} → {archive} ({size:,} bytes)")
    if args.include_credentials:
        print("[jaeger backup]   ⚠  archive includes credentials/ — "
              "store it somewhere safe.", file=sys.stderr)
    if not args.include_skills:
        print("[jaeger backup]   (skills/ excluded per --no-skills)")
    return 0


def _cmd_restore_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger restore", add_help=False)
    parser.add_argument("archive", nargs="?", default=None)
    parser.add_argument("--name", default=None,
                        help="restore under a different name (default: from archive)")
    parser.add_argument("--force", action="store_true",
                        help="back up + replace if an instance with this name exists")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger restore [<archive.zip>] [--name NEW] [--force]\n"
            "  Bareword: prompts to pick from ~/.jaeger/backups/.\n",
            file=sys.stderr,
        )
        return 0

    if args.archive is None:
        picked = _pick_backup_interactively()
        if picked is None:
            return 1
        archive = picked
    else:
        archive = Path(args.archive).expanduser()
    try:
        target = restore_instance(archive, name_override=args.name,
                                  force=args.force)
    except RestoreError as exc:
        print(f"[jaeger restore] {exc}", file=sys.stderr)
        return 1

    print(f"[jaeger restore] restored to {target}")
    print("[jaeger restore]   review identity.yaml + config.yaml + "
          "credentials/ before running.")
    return 0


__all__ = [
    "RestoreError",
    "backup_instance",
    "restore_instance",
    "_cmd_backup_argv",
    "_cmd_restore_argv",
]
