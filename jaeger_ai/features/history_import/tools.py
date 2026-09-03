"""Agent-facing unified history import tools."""

from dataclasses import asdict

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from jaeger_ai.core.sessions import get_store

from .service import HistoryImportService


def _service() -> HistoryImportService:
    store = get_store()
    if store is None:
        raise RuntimeError("Jaeger instance session store is not bound")
    return HistoryImportService(store)


@register_tool_from_function(side_effect="read")
def history_import_scan() -> dict:
    """Count discoverable ARES, Claude, Codex, Gemini, and Grok transcripts without
    reading their message content or changing Jaeger state."""
    return {"ok": True, "sources": _service().scan()}


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="history_import",
    operation="history_import",
    summary="import external transcripts into Jaeger's session database",
)
def history_import(
    sources: list[str] | None = None,
    limit_per_source: int | None = None,
) -> dict:
    """Import ARES and external CLI transcripts into Jaeger's canonical searchable
    session history. Imports are idempotent and preserve source provenance."""
    selected = {str(item).strip().lower() for item in sources or [] if str(item).strip()}
    reports = _service().import_all(
        selected=selected or None,
        limit_per_source=limit_per_source,
    )
    return {"ok": True, "reports": [asdict(report) for report in reports]}
