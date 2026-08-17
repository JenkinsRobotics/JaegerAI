"""One-way migration from the retired JaegerOS-branded state directory."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()
_LEGACY_STATE_DIR_NAME = ".jaeger_os"


def migrate_operator_state(install_root: Path, destination: Path) -> Path:
    """Atomically move legacy state and leave a compatibility symlink.

    No data is deleted. If either layout is already usable, this is idempotent.
    """
    legacy = install_root / _LEGACY_STATE_DIR_NAME
    if destination.exists() or not legacy.exists() or legacy.is_symlink():
        return destination
    with _LOCK:
        if destination.exists() or not legacy.exists() or legacy.is_symlink():
            return destination
        try:
            os.replace(legacy, destination)
            legacy.symlink_to(destination.name, target_is_directory=True)
            logger.info("Migrated JaegerAI operator state to %s", destination)
        except OSError:
            logger.warning("Could not migrate JaegerAI operator state to %s", destination, exc_info=True)
    return destination


__all__ = ["migrate_operator_state"]
