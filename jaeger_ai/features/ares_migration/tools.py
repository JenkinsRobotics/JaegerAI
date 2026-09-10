"""Agent-facing ARES state migration and retirement-gate tools."""

from pathlib import Path

from jaeger_agent.workspace import (
    SandboxError,
    _resolve_under,
    get_effective_workspace_dir,
)
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from jaeger_ai.core.ares_interop import ares_migration_source
from jaeger_ai.core.sessions import get_store

from .service import AresMigrationService, MigrationError


def _service(source: str) -> AresMigrationService:
    from jaeger_ai.main import _pipeline

    layout = _pipeline.get("layout")
    sessions = get_store()
    if layout is None or sessions is None:
        raise RuntimeError("Jaeger instance is not bound")
    root = ares_migration_source() if source == "~/.ares" else Path(source).expanduser()
    return AresMigrationService(root, layout, sessions)


@register_tool_from_function(side_effect="read")
def ares_migration_audit(source: str = "~/.ares") -> dict:
    """Inventory executable ARES state before migration without modifying it."""
    try:
        return {"ok": True, **_service(source).audit()}
    except (MigrationError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="ares_migration",
    operation="ares_migrate",
    summary="import ARES state into Jaeger's durable stores",
)
def ares_migrate(source: str = "~/.ares") -> dict:
    """Idempotently import ARES sessions, documents, schedules, worker health,
    passkeys, and Kanban state. This never modifies or removes ARES."""
    try:
        return _service(source).migrate()
    except (MigrationError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="ares_migration",
    operation="ares_backup",
    summary="write a restricted archive of ARES state",
)
def ares_backup(
    output: str,
    source: str = "~/.ares",
    include_secrets: bool = False,
) -> dict:
    """Create a restricted ARES state backup for the retirement gate."""
    try:
        target = _resolve_under(get_effective_workspace_dir(), output)
        return {"ok": True, **_service(source).create_backup(
            target, include_secrets=include_secrets
        )}
    except (MigrationError, OSError, SandboxError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="read")
def ares_retirement_rehearsal(source: str = "~/.ares", backup: str = "") -> dict:
    """Evaluate cutover gates without stopping, changing, or deleting ARES."""
    try:
        return {"ok": True, **_service(source).rehearse_retirement(
            Path(backup).expanduser() if backup else None
        )}
    except (MigrationError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
