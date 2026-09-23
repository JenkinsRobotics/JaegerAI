"""One-way migration from the retired JaegerOS-branded state directory.

``<install_root>/.jaeger_os`` -> ``<install_root>/.jaeger_ai``, through the
phased, verified, resumable engine in :mod:`.state_migration`. The legacy
directory is left untouched (no compatibility symlink: nothing reads the old
path once the destination is active), and a failed migration refuses to
start rather than silently continuing with an empty state root.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .state_migration import (
    MigrationBusy,
    MigrationConflict,
    MigrationFailed,
    migrate_directory,
    work_dir_for,
)

logger = logging.getLogger(__name__)
_LEGACY_STATE_DIR_NAME = ".jaeger_os"


def migrate_operator_state(install_root: Path, destination: Path) -> Path:
    """Return ``destination``, migrating legacy state into it first if needed.

    Idempotent: once the destination is active this is a cheap no-op.

    Raises:
        RuntimeError: the migration conflicted, is running elsewhere, or
            failed. The message names the manifest to inspect; the legacy
            source is intact and re-running resumes.
    """
    legacy = install_root / _LEGACY_STATE_DIR_NAME
    manifest = work_dir_for(destination) / "manifest.json"
    in_progress = False
    if manifest.is_file():
        try:
            in_progress = json.loads(manifest.read_text(encoding="utf-8")).get("phase") != "complete"
        except (OSError, ValueError):
            in_progress = True
    if destination.exists() and not in_progress:
        # The destination is the active state (activated by this engine, or
        # by the pre-engine migrator). A leftover legacy directory beside it
        # is not merged or deleted; it is simply no longer read.
        return destination
    try:
        result = migrate_directory(legacy, destination, kind="jaeger_os_to_jaeger_ai")
    except (MigrationConflict, MigrationBusy, MigrationFailed) as exc:
        raise RuntimeError(
            f"operator state migration {legacy} -> {destination} did not complete: {exc}. "
            f"Legacy state is untouched; see {destination.name}.migration/manifest.json "
            "beside it, then re-run."
        ) from exc
    if result.status == "migrated":
        logger.info("Migrated JaegerAI operator state to %s (%s)", destination, result.details)
    return destination


__all__ = ["migrate_operator_state"]
