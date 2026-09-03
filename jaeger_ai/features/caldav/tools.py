"""Agent-facing generic CalDAV tools."""

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from . import service


def _bind() -> None:
    from jaeger_ai.main import _pipeline

    layout = _pipeline.get("layout")
    if layout is None:
        raise RuntimeError("Jaeger instance is not bound")
    service.bind(layout)


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="caldav",
    operation="caldav_configure",
    summary="store CalDAV configuration and a calendar credential",
)
def caldav_configure(
    calendar_url: str,
    username: str,
    password: str = "",
    profile: str = "default",
) -> dict:
    """Configure a generic CalDAV calendar; the password is stored as a
    permission-checked Jaeger credential and never returned."""
    try:
        _bind()
        return {"ok": True, **service.configure(
            profile, calendar_url=calendar_url, username=username, password=password or None
        )}
    except (OSError, service.CalDavError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="read")
def caldav_sync(profile: str = "default") -> dict:
    """Synchronize a configured generic CalDAV calendar into its local cache."""
    try:
        _bind()
        return {"ok": True, **service.sync(profile)}
    except (OSError, service.CalDavError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="read")
def caldav_events(profile: str = "default") -> dict:
    """List cached CalDAV events without making a network request."""
    _bind()
    return {"ok": True, **service.list_cached_events(profile)}


@register_tool_from_function(side_effect="external")
@requires_tier(
    PermissionTier.EXTERNAL_EFFECT,
    skill="caldav",
    operation="caldav_put_event",
    summary="create or update an event on an external calendar",
)
def caldav_put_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    uid: str = "",
    etag: str = "",
    profile: str = "default",
) -> dict:
    """Create or update one event in a configured generic CalDAV calendar."""
    try:
        _bind()
        return {"ok": True, **service.put_event(
            profile,
            uid=uid or None,
            summary=summary,
            start=start,
            end=end,
            description=description,
            etag=etag or None,
        )}
    except (OSError, service.CalDavError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="external")
@requires_tier(
    PermissionTier.EXTERNAL_EFFECT,
    skill="caldav",
    operation="caldav_delete_event",
    summary="delete an event from an external calendar",
)
def caldav_delete_event(
    uid: str,
    etag: str = "",
    profile: str = "default",
) -> dict:
    """Delete one event from a configured generic CalDAV calendar."""
    try:
        _bind()
        return {"ok": True, **service.delete_event(profile, uid=uid, etag=etag or None)}
    except (OSError, service.CalDavError) as exc:
        return {"ok": False, "error": str(exc)}
