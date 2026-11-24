"""jaeger-macos — Pure macOS OS adapter library (no product routes or permissions)."""

from .appleevents import appleevents_lock, escape_applescript, run_applescript
from .imessage import SEND_IMESSAGE_SCRIPT, decode_attributed_body, send_imessage
from .mail import ALIAS_GROUPS, MAIL_RESOLVER_AS, alias_candidates, resolve_mailbox_call
from .tcc import probe_tcc_status, request_tcc_permissions

__all__ = [
    "appleevents_lock",
    "escape_applescript",
    "run_applescript",
    "ALIAS_GROUPS",
    "MAIL_RESOLVER_AS",
    "alias_candidates",
    "resolve_mailbox_call",
    "SEND_IMESSAGE_SCRIPT",
    "decode_attributed_body",
    "send_imessage",
    "probe_tcc_status",
    "request_tcc_permissions",
]
