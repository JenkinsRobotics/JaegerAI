"""Generic CalDAV feature."""

from .service import (
    CalDavError,
    bind,
    configure,
    delete_event,
    list_cached_events,
    put_event,
    sync,
)

__all__ = [
    "CalDavError",
    "bind",
    "configure",
    "delete_event",
    "list_cached_events",
    "put_event",
    "sync",
]
