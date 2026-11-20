"""Verified state audit, backup/archive, restore, and clean personal profile lifecycle (§2 & §8).

Safety invariants:
  - ``audit_state_root`` is strictly read-only.
  - ``archive_state_root`` uses SQLite's online backup API (safe with WAL),
    runs ``PRAGMA integrity_check`` on every archived DB, computes SHA-256
    checksums for every archived file, and NEVER copies plaintext secrets.
  - ``verify_archive`` independently validates checksums, SQLite integrity,
    and secret exclusion before any restore is permitted.
  - ``create_clean_personal_profile`` builds a clean Truth workspace with zero
    dev/benchmark clutter and records ``install_mode`` (``fresh_install`` vs
    ``migrated_clean_personal``).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import yaml

# Relative path prefixes/names treated as secrets and ALWAYS excluded from archives.
SECRET_NAMES: frozenset[str] = frozenset({
    "secrets.env",
    "secrets",
    "caller_tokens",
    "credentials",
    ".env",
})

DEV_INSTANCE_PREFIXES: tuple[str, ...] = (
    "mac-acceptance-",
    "mac-controls-",
    "jaeger-design-style",
    "jaeger-gateway-webui",
    "jaeger-mac-app",
    "jager-system-engineer",
    "reverse-engineer",
    "builder",
    "designer",
    "everyday",
    "finance",
    "gateway",
    "health",
    "query",
    "research",
    "researcher",
    "reviewer",
    "surfaces",
)

DEV_TOP_DIRS: frozenset[str] = frozenset({
    "worktrees",
    "compare",
    "delegate_receipts",
    "deck-events",
    "agent-undo-trash",
    "hermes-webui-agent",
})

CONFIG_FILES: frozenset[str] = frozenset({
    "active_instance",
    "agent-network.json",
    "agent-webhook-host.txt",
    "conversation-permissions.json",
    "dashboard.json",
    "deployed-manifest.json",
    "droid.json",
    "config.yaml",
    "mcp.json",
    "permissions.json",
    "framework_grants.json",
    "provider_certifications.json",
    "shell-hooks-allowlist.json",
    "distribution.yaml",
    "manifest.json",
    "first_boot.yaml",
})

IDENTITY_FILES: frozenset[str] = frozenset({
    "entity_identity.json",
    "identity.yaml",
    "soul.md",
    "active_character",
    "knowledge.sqlite3",
})


def _is_secret_rel(rel: Path) -> bool:
    parts = rel.parts
    for part in parts:
        low = part.lower()
        if low in SECRET_NAMES or low.endswith(".key") or low.endswith(".pem"):
            return True
    return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sqlite_integrity(db_path: Path) -> tuple[bool, str]:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            msg = str(row[0]) if row else "unknown"
            return msg.lower() == "ok", msg
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _sqlite_backup(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def audit_state_root(state_root: Path | str) -> dict[str, Any]:
    """Strictly read-only classification of an existing Jaeger state directory."""
    root = Path(state_root).expanduser()
    result: dict[str, Any] = {
        "state_root": str(root),
        "exists": root.exists(),
        "audited_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "categories": {
            "personal_user_data": [],
            "development_and_testing": [],
            "application_config": [],
            "persistent_identity_and_knowledge": [],
            "secrets_excluded_in_place": [],
            "obsolete_or_cache": [],
        },
        "sqlite_summary": [],
    }
    if not root.exists():
        return result

    for entry in sorted(root.iterdir()):
        name = entry.name
        rel = Path(name)
        if _is_secret_rel(rel):
            result["categories"]["secrets_excluded_in_place"].append(name)
        elif name in IDENTITY_FILES:
            result["categories"]["persistent_identity_and_knowledge"].append(name)
        elif name in CONFIG_FILES or name in {"config", "control"}:
            result["categories"]["application_config"].append(name)
        elif name in DEV_TOP_DIRS or ".backup-" in name or name.endswith(".bak"):
            result["categories"]["development_and_testing"].append(name)
        elif name in {"venv", "voice-venv", "logs", "cache", "tmp"} or name.endswith(("-wal", "-shm", ".lock")):
            result["categories"]["obsolete_or_cache"].append(name)
        elif name in {"gateway_sessions.sqlite3", "human_needs.sqlite3", "companion_memory.sqlite3", "documents", "finance", "attachments", "memory"}:
            result["categories"]["personal_user_data"].append(name)
        elif name == "instances" and entry.is_dir():
            for inst in sorted(entry.iterdir()):
                if not inst.is_dir():
                    continue
                if any(inst.name == p or inst.name.startswith(p) for p in DEV_INSTANCE_PREFIXES):
                    result["categories"]["development_and_testing"].append(f"instances/{inst.name}")
                else:
                    result["categories"]["application_config"].append(f"instances/{inst.name}")
                    for bak in sorted(inst.glob("*.bak*")):
                        result["categories"]["development_and_testing"].append(f"instances/{inst.name}/{bak.name}")
        else:
            result["categories"]["personal_user_data"].append(name)

    for db in sorted(root.glob("*.sqlite*")):
        if db.name.endswith(("-wal", "-shm")):
            continue
        ok, msg = _sqlite_integrity(db)
        counts: dict[str, int] = {}
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                for (tbl,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                    counts[tbl] = int(conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0])
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            pass
        result["sqlite_summary"].append({
            "name": db.name,
            "size_bytes": db.stat().st_size,
            "integrity_ok": ok,
            "integrity_detail": msg,
            "table_counts": counts,
        })
    return result


def archive_state_root(
    state_root: Path | str,
    archive_dir: Path | str,
    *,
    include_worktrees: bool = False,
) -> dict[str, Any]:
    """Create a versioned, checksummed, secret-free archive of ``state_root``."""
    src_root = Path(state_root).expanduser().resolve()
    dst_root = Path(archive_dir).expanduser().resolve()
    if not src_root.exists():
        raise FileNotFoundError(f"State root does not exist: {src_root}")
    if dst_root.exists() and any(dst_root.iterdir()):
        raise FileExistsError(f"Archive destination already exists and is non-empty: {dst_root}")

    payload_root = dst_root / "payload"
    payload_root.mkdir(parents=True, exist_ok=True)

    archived_files: list[dict[str, Any]] = []
    sqlite_checks: list[dict[str, Any]] = []
    excluded_secrets: list[str] = []
    skipped_runtime: list[str] = []

    skip_top_dirs = {"venv", "voice-venv", "backups", "archive", "browser"}
    if not include_worktrees:
        skip_top_dirs.add("worktrees")

    for path in sorted(src_root.rglob("*")):
        rel = path.relative_to(src_root)
        if not rel.parts:
            continue
        if rel.parts[0] in skip_top_dirs:
            continue
        if _is_secret_rel(rel):
            excluded_secrets.append(rel.as_posix())
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if path.name.endswith(("-wal", "-shm", ".lock", ".sock")) or ".lock." in path.name or path.name == ".lock":
            skipped_runtime.append(rel.as_posix())
            continue
        if "venv" in rel.parts or "__pycache__" in rel.parts or "run" in rel.parts:
            skipped_runtime.append(rel.as_posix())
            continue

        out_file = payload_root / rel
        out_file.parent.mkdir(parents=True, exist_ok=True)

        if path.suffix in {".sqlite3", ".sqlite", ".db"} and path.stat().st_size > 0:
            _sqlite_backup(path, out_file)
            ok, msg = _sqlite_integrity(out_file)
            sqlite_checks.append({"path": rel.as_posix(), "integrity_ok": ok, "detail": msg})
            if not ok:
                raise RuntimeError(f"SQLite integrity check failed for archived {rel}: {msg}")
        else:
            shutil.copy2(path, out_file)

        archived_files.append({
            "path": rel.as_posix(),
            "size_bytes": out_file.stat().st_size,
            "sha256": _sha256(out_file),
        })

    manifest = {
        "schema": "jaeger.state_archive.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_state_root": str(src_root),
        "file_count": len(archived_files),
        "sqlite_checks": sqlite_checks,
        "excluded_secrets": sorted(set(excluded_secrets)),
        "skipped_runtime_count": len(skipped_runtime),
        "files": archived_files,
    }
    (dst_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (dst_root / "RESTORE.md").write_text(
        "# JaegerAI Archive Restoration Instructions\n\n"
        f"- Created: `{manifest['created_at']}`\n"
        f"- Source: `{src_root}`\n"
        f"- Files verified (SHA-256): `{len(archived_files)}`\n"
        f"- SQLite DBs verified (`PRAGMA integrity_check`): `{len(sqlite_checks)}`\n"
        "- Secrets (`secrets.env`, `secrets/`, `caller_tokens/`, `credentials/`) were **NOT** copied into this archive; preserve them in place.\n\n"
        "## Restore Steps\n"
        "1. Stop Jaeger services (`launchctl bootout` or pause gateway).\n"
        "2. Verify archive integrity via `verify_archive(archive_dir)`.\n"
        "3. Restore payload via `restore_archive(archive_dir, target_state_root, allow_existing=True)` (secrets in target remain preserved).\n"
        "4. Restart Gateway and verify `/health`.\n",
        encoding="utf-8",
    )
    return manifest


def verify_archive(archive_dir: Path | str) -> dict[str, Any]:
    """Verify SHA-256 integrity, SQLite consistency, and secret exclusion of an archive."""
    root = Path(archive_dir).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return {"ok": False, "error": "manifest.json missing"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload_root = root / "payload"
    mismatches: list[str] = []
    missing: list[str] = []
    secret_leaks: list[str] = []
    sqlite_failures: list[str] = []

    for entry in manifest.get("files") or []:
        rel = Path(entry["path"])
        if _is_secret_rel(rel):
            secret_leaks.append(entry["path"])
        target = payload_root / rel
        if not target.is_file():
            missing.append(entry["path"])
            continue
        if _sha256(target) != entry["sha256"]:
            mismatches.append(entry["path"])
        if target.suffix in {".sqlite3", ".sqlite", ".db"} and target.stat().st_size > 0:
            ok, msg = _sqlite_integrity(target)
            if not ok:
                sqlite_failures.append(f"{entry['path']}: {msg}")

    # Also scan payload for any unexpected secret files not listed in manifest.
    for path in payload_root.rglob("*"):
        if path.is_file() and _is_secret_rel(path.relative_to(payload_root)):
            secret_leaks.append(path.relative_to(payload_root).as_posix())

    ok = not (mismatches or missing or secret_leaks or sqlite_failures)
    return {
        "ok": ok,
        "archive_dir": str(root),
        "verified_files": len(manifest.get("files") or []),
        "mismatches": mismatches,
        "missing": missing,
        "secret_leaks": sorted(set(secret_leaks)),
        "sqlite_failures": sqlite_failures,
        "excluded_secrets": manifest.get("excluded_secrets") or [],
    }


def restore_archive(
    archive_dir: Path | str,
    target_state_root: Path | str,
    *,
    allow_existing: bool = False,
) -> dict[str, Any]:
    """Restore a verified archive into ``target_state_root`` without touching live secrets."""
    check = verify_archive(archive_dir)
    if not check.get("ok"):
        raise RuntimeError(f"Refusing to restore invalid archive: {check}")
    src_payload = Path(archive_dir).expanduser().resolve() / "payload"
    dst = Path(target_state_root).expanduser().resolve()
    if dst.exists() and any(dst.iterdir()) and not allow_existing:
        raise FileExistsError(f"Target state root is non-empty: {dst} (pass allow_existing=True)")
    dst.mkdir(parents=True, exist_ok=True)
    restored = 0
    for path in sorted(src_payload.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_payload)
        if _is_secret_rel(rel):
            continue  # Never overwrite live secrets
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        restored += 1
    return {"ok": True, "restored_files": restored, "target_state_root": str(dst)}


def create_clean_personal_profile(
    target_state_root: Path | str,
    *,
    instance_name: str = "jaeger",
    companion_name: str = "Truth",
    source_config_path: Path | str | None = None,
    install_mode: str | None = None,
    autonomy: str = "auto",
    quiet_start_hour: int = 22,
    quiet_end_hour: int = 7,
    heartbeat_interval_minutes: int = 30,
    initial_goals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Initialize a clean personal-use JaegerAI profile centered on Truth.

    Contains:
      - Default persistent companion identity: Truth (empty conversation/task history).
      - Zero dev/benchmark sessions, zero synthetic personal memories, zero stale alerts.
      - Clean SQLite stores initialized with schema & passing ``PRAGMA integrity_check``.
      - Model/provider settings carried over safely when migrating from ``source_config_path``
        (never copying plaintext secrets).
      - Valid ``first_boot.yaml`` distinguishing ``fresh_install`` vs ``migrated_clean_personal``.
    """
    root = Path(target_state_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    inst_dir = root / "instances" / instance_name
    from jaeger_ai.core.entity.identity import EntityIdentity
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, Identity, dump_yaml, load_yaml
    from jaeger_ai.core.runtime.autonomy import normalize_autonomy, permissions_mode_for
    from jaeger_ai.core.world.store import SqliteWorldStore
    from jaeger_ai.features.human_needs.store import HumanNeedsStore
    from jaeger_ai.features.personality.character import bind_character

    layout = InstanceLayout(root=inst_dir)
    layout.ensure_dirs()
    (root / "active_instance").write_text(f"{instance_name}\n", encoding="utf-8")

    # Determine install mode cleanly.
    mode = install_mode or ("migrated_clean_personal" if source_config_path else "fresh_install")

    # Build clean Config, optionally carrying forward non-secret provider/model choices.
    if source_config_path and Path(source_config_path).is_file():
        src_cfg = load_yaml(Path(source_config_path), Config)
        cfg = src_cfg.model_copy(deep=True)
        cfg.instance_name = instance_name
    else:
        cfg = Config(instance_name=instance_name, model={"model_path": "unconfigured"})
        cfg.external_model.enabled = True
        cfg.external_model.provider = "ollama"
        cfg.external_model.model = "mistral-large-4:cloud"
        cfg.external_model.base_url = "http://127.0.0.1:11434/v1"

    norm_auto = normalize_autonomy(autonomy) or "scoped"
    cfg.automation.autonomy = norm_auto
    cfg.permissions.mode = permissions_mode_for(norm_auto)
    dump_yaml(layout.config_path, cfg)

    # Persistent entity identity (Truth default).
    from jaeger_ai.features.personality.character import characters_root, load_character
    ent = EntityIdentity.create_default(instance_name, display_name=companion_name.strip() or "Truth")
    ent.save_to_file(root / "entity_identity.json")

    truth_char = load_character(characters_root() / "truth")
    ident = Identity(
        name=ent.display_name,
        role=truth_char.role or "Persistent truth-seeking personal intelligence dedicated to human flourishing.",
        voice_id=truth_char.voice_id or "af_heart",
        voice_tone=(truth_char.voice_tone or "calm, candid, warm, grounded in evidence")[:64],
        personality=(truth_char.personality.description or "Evidence-grounded, candid, and supportive of human flourishing.")[:2048],
    )
    dump_yaml(layout.identity_path, ident)
    if truth_char.soul:
        (layout.root / "soul.md").write_text(truth_char.soul, encoding="utf-8")
    bind_character(layout.root, "truth")

    # Initialize clean, empty SQLite stores (zero dev/test clutter).
    from jaeger_ai.core.tasks.store import SqliteDurableTaskStore
    GatewaySessionStore(root / "gateway_sessions.sqlite3")
    SqliteDurableTaskStore(root / "gateway_sessions.sqlite3")
    SqliteWorldStore(root / "knowledge.sqlite3")
    hn = HumanNeedsStore(root / "human_needs.sqlite3")
    hn.update_preferences({
        "proactive_enabled": True,
        "quiet_start_hour": int(quiet_start_hour),
        "quiet_end_hour": int(quiet_end_hour),
        "heartbeat_interval_minutes": int(heartbeat_interval_minutes),
        "digest_enabled": True,
    })
    seeded_goals = []
    for g in initial_goals or []:
        seeded_goals.append(
            hn.add_goal(
                title=str(g.get("title") or ""),
                dimension=str(g.get("dimension") or "self_actualization"),
                priority=int(g.get("priority", 3)),
                notes=str(g.get("notes") or ""),
                success_metric=str(g.get("success_metric") or ""),
            )
        )

    # Write clean first-run onboarding state record.
    first_boot_payload = {
        "schema_version": 4,
        "status": "NOT_STARTED",
        "install_mode": mode,
        "companion_name": ent.display_name,
        "character_id": "truth",
        "autonomy": norm_auto,
        "quiet_hours": {"start": int(quiet_start_hour), "end": int(quiet_end_hour)},
        "heartbeat_interval_minutes": int(heartbeat_interval_minutes),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (inst_dir / "first_boot.yaml").write_text(yaml.safe_dump(first_boot_payload, sort_keys=False), encoding="utf-8")

    # Verify every initialized SQLite DB passes integrity check.
    db_checks = {}
    for db_name in ("gateway_sessions.sqlite3", "knowledge.sqlite3", "human_needs.sqlite3"):
        ok, msg = _sqlite_integrity(root / db_name)
        db_checks[db_name] = {"ok": ok, "detail": msg}
        if not ok:
            raise RuntimeError(f"Clean profile DB failed integrity check: {db_name}: {msg}")

    return {
        "ok": True,
        "state_root": str(root),
        "instance_dir": str(inst_dir),
        "install_mode": mode,
        "companion_name": ent.display_name,
        "entity_id": ent.entity_id,
        "autonomy": norm_auto,
        "seeded_goals": len(seeded_goals),
        "db_checks": db_checks,
    }
