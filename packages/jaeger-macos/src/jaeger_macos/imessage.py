"""Pure macOS iMessage typedstream decoder & locked Messages.app send helper."""

from __future__ import annotations

from .appleevents import run_applescript

SEND_IMESSAGE_SCRIPT = r'''
on run argv
    set targetHandle to item 1 of argv
    set msgText to item 2 of argv
    set svcName to item 3 of argv
    tell application "Messages"
        try
            if svcName is "SMS" then
                set targetAccount to first account whose service type = SMS
            else
                set targetAccount to first account whose service type = iMessage
            end if
            send msgText to participant targetHandle of targetAccount
        on error
            if svcName is "SMS" then
                set targetService to first service whose service type = SMS
            else
                set targetService to first service whose service type = iMessage
            end if
            send msgText to buddy targetHandle of targetService
        end try
    end tell
end run
'''


def decode_attributed_body(blob: bytes | None) -> str:
    """Plain text from a typedstream ``attributedBody`` (macOS 13+ often leaves ``text`` NULL)."""
    if not blob:
        return ""
    try:
        data = bytes(blob)
        idx = data.find(b"NSString")
        if idx < 0:
            return ""
        rest = data[idx + len(b"NSString"):]
        plus = rest.find(b"+")
        if plus < 0:
            return ""
        rest = rest[plus + 1:]
        length = rest[0]
        offset = 1
        if length == 0x81:
            length = int.from_bytes(rest[1:3], "little")
            offset = 3
        elif length == 0x82:
            length = int.from_bytes(rest[1:5], "little")
            offset = 5
        return rest[offset:offset + length].decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        return ""


def send_imessage(
    handle: str,
    text: str,
    *,
    service: str = "iMessage",
    timeout_seconds: float = 15.0,
) -> dict:
    """Send a message via Messages.app under the cross-process AppleEvents lock."""
    return run_applescript(
        SEND_IMESSAGE_SCRIPT,
        timeout_seconds=timeout_seconds,
        target="messages",
        argv=[handle, text, service],
    )
