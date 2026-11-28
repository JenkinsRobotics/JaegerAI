"""jaeger-macos — Pure macOS OS adapter library (no product routes or permissions)."""

from .appleevents import appleevents_lock, escape_applescript, run_applescript
from .calendar import (
    LIST_CALENDARS_SCRIPT,
    create_calendar_event,
    list_calendars,
    list_upcoming_events,
)
from .computer_guard import (
    DEFAULT_DENY_APPS,
    DEFAULT_DENY_TITLE_TOKENS,
    ComputerUseAuditRecord,
    ComputerUseDecision,
    check_app_automation_allowed,
)
from .imessage import SEND_IMESSAGE_SCRIPT, decode_attributed_body, send_imessage
from .mail import ALIAS_GROUPS, MAIL_RESOLVER_AS, alias_candidates, resolve_mailbox_call
from .notes import (
    LIST_FOLDERS_SCRIPT,
    create_note,
    list_note_folders,
    read_note,
    search_notes,
)
from .reminders import (
    LIST_REMINDER_LISTS_SCRIPT,
    complete_reminder,
    create_reminder,
    list_reminder_lists,
    list_reminders,
)
from .tcc import probe_tcc_status, request_tcc_permissions

__all__ = [
    "appleevents_lock",
    "escape_applescript",
    "run_applescript",
    "ALIAS_GROUPS",
    "MAIL_RESOLVER_AS",
    "alias_candidates",
    "resolve_mailbox_call",
    "LIST_CALENDARS_SCRIPT",
    "list_calendars",
    "list_upcoming_events",
    "create_calendar_event",
    "LIST_REMINDER_LISTS_SCRIPT",
    "list_reminder_lists",
    "list_reminders",
    "create_reminder",
    "complete_reminder",
    "LIST_FOLDERS_SCRIPT",
    "list_note_folders",
    "search_notes",
    "read_note",
    "create_note",
    "DEFAULT_DENY_APPS",
    "DEFAULT_DENY_TITLE_TOKENS",
    "ComputerUseAuditRecord",
    "ComputerUseDecision",
    "check_app_automation_allowed",
    "SEND_IMESSAGE_SCRIPT",
    "decode_attributed_body",
    "send_imessage",
    "probe_tcc_status",
    "request_tcc_permissions",
]
