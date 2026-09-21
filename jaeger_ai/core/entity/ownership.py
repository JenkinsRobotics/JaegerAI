"""EntityRuntime ownership and instance-scoped state resolution.

Canonical topology (JAEGER PRODUCTION OS SPEC):
    Gateway process = OWNER (one per instance)
    CLI / WebUI / Bridge / MCP = ATTACHED_CLIENT
    pytest = TEST

ATTACHED_CLIENT must not mint identity, schedule heartbeat/sensors/sleep,
or act as a second runtime authority.
"""

from __future__ import annotations

from enum import Enum
import logging
import os
from pathlib import Path
import shutil
from typing import Any

from jaeger_ai.core.instance.instance import (
    InstanceLayout,
    default_instance_name,
    operator_state_root,
    resolve_instance_dir,
)

logger = logging.getLogger("jaeger.entity.ownership")


class EntityRuntimeMode(str, Enum):
    OWNER = "owner"
    ATTACHED_CLIENT = "attached_client"
    TEST = "test"


def infer_runtime_mode() -> EntityRuntimeMode:
    explicit = (os.environ.get("JAEGER_RUNTIME_MODE") or "").strip().lower()
    if explicit in {m.value for m in EntityRuntimeMode}:
        return EntityRuntimeMode(explicit)
    if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("JAEGER_NO_ATTACH") == "1":
        return EntityRuntimeMode.TEST
    import sys
    argv0 = " ".join(sys.argv[:3])
    if "jaeger_ai.core.gateway.server" in argv0 or "gateway.server" in argv0:
        return EntityRuntimeMode.OWNER
    return EntityRuntimeMode.ATTACHED_CLIENT


def instance_layout(instance_name: str | None = None) -> InstanceLayout:
    layout = InstanceLayout(root=resolve_instance_dir(instance_name))
    layout.ensure_dirs()
    return layout


def runtime_state_root(state_root: Path | str | None = None) -> Path:
    """Agent-persistent fabric root: instance memory/, unless an explicit root is given."""
    if state_root is not None:
        path = Path(state_root)
        path.mkdir(parents=True, exist_ok=True)
        return path
    layout = instance_layout()
    migrate_legacy_entity_state(layout)
    return layout.memory_dir


def migrate_legacy_entity_state(layout: InstanceLayout) -> None:
    """Move operator-global entity files into the instance memory directory once."""
    layout.ensure_dirs()
    op = operator_state_root()
    mapping = (
        (op / "entity_identity.json", layout.entity_identity_path),
        (op / "entity_events.sqlite3", layout.event_store_path),
        (op / "structured_reflections.json", layout.reflections_path),
        (op / "entity.resident.lock", layout.resident_lock_path),
    )
    for src, dest in mapping:
        try:
            if src.is_file() and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                logger.info("Migrated %s -> %s", src, dest)
        except OSError as exc:
            logger.warning("Legacy entity state migration skipped for %s: %s", src, exc)


def ownership_projection(runtime: Any) -> dict[str, Any]:
    identity = getattr(runtime, "identity", None)
    store = getattr(runtime, "event_store", None)
    latest = 0
    count = 0
    try:
        count = int(store.count()) if store is not None and hasattr(store, "count") else int(
            getattr(runtime.current_state, "total_events_processed", 0)
        )
    except Exception:
        count = int(getattr(getattr(runtime, "current_state", None), "total_events_processed", 0) or 0)
    try:
        if store is not None:
            latest = int(store.latest_id())
    except Exception:
        latest = count
    layout = getattr(runtime, "layout", None)
    return {
        "entity_id": getattr(identity, "entity_id", None),
        "instance_id": getattr(identity, "instance_name", None) or default_instance_name(),
        "state_root": str(getattr(runtime, "state_root", "")),
        "event_store": str(getattr(store, "path", "") or ""),
        "latest_event_sequence": latest,
        "event_count": count,
        "mode": getattr(getattr(runtime, "mode", None), "value", None) or str(getattr(runtime, "mode", "")),
        "resident": bool(getattr(runtime, "is_resident", False)),
        "instance_root": str(layout.root) if layout is not None else None,
    }
