"""Native macOS automation tools for JaegerAI / ARES.

Directly bridges AppleScript / JXA (Calendar, Reminders, Mail, Safari, Music, Notifications),
Apple Shortcuts CLI (`shortcuts`), and native Spotlight indexing (`mdfind`).
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any


def _run_osascript(script: str, timeout_s: float = 10.0) -> tuple[bool, str]:
    """Execute an AppleScript snippet via osascript."""
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        return False, proc.stderr.strip() or f"osascript exited with code {proc.returncode}"
    except subprocess.TimeoutExpired:
        return False, f"osascript timed out after {timeout_s}s"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def macos_automation(
    target: str,
    action: str = "read",
    title: str = "",
    message: str = "",
    due_date: str = "",
    start_date: str = "",
    end_date: str = "",
    to_recipient: str = "",
    subject: str = "",
    body: str = "",
    sound: str = "Glass",
) -> dict[str, Any]:
    """Control native macOS applications via safe Apple Events."""
    t = (target or "").strip().lower()
    act = (action or "").strip().lower()

    if t in {"notification", "notify", "banner"}:
        msg = message or title or "ARES task complete"
        tit = title or "ARES Executive"
        snd = f'sound name "{sound}"' if sound else ""
        script = f'display notification "{msg}" with title "{tit}" {snd}'
        ok, res = _run_osascript(script)
        return {"success": ok, "target": "notification", "result": res or "Notification displayed"}

    if t in {"calendar", "cal", "events"}:
        if act in {"list", "read", "today", "agenda"}:
            script = """
            set output to ""
            tell application "Calendar"
                set today to current date
                set tomorrow to today + (1 * days)
                repeat with c in calendars
                    tell c
                        set evList to (every event whose start date ≥ today and start date < tomorrow)
                        repeat with ev in evList
                            set output to output & (summary of ev) & " [" & ((start date of ev) as string) & "] | "
                        end repeat
                    end tell
                end repeat
            end tell
            return output
            """
            ok, res = _run_osascript(script)
            return {"success": ok, "target": "calendar", "events": res or "No events scheduled for today"}
        elif act in {"create", "add", "new"}:
            if not title:
                return {"success": False, "error": "title is required to create a calendar event"}
            script = f"""
            tell application "Calendar"
                tell calendar 1
                    make new event with properties {{summary:"{title}", start date:(current date + (1 * hours)), end date:(current date + (2 * hours))}}
                end tell
            end tell
            """
            ok, res = _run_osascript(script)
            return {"success": ok, "target": "calendar", "result": f"Created event: {title}" if ok else res}

    if t in {"reminders", "reminder", "todo"}:
        if act in {"list", "read", "pending"}:
            script = """
            set output to ""
            tell application "Reminders"
                set remList to (every reminder whose completed is false)
                repeat with r in remList
                    set output to output & (name of r) & " | "
                end repeat
            end tell
            return output
            """
            ok, res = _run_osascript(script)
            return {"success": ok, "target": "reminders", "reminders": res or "No pending reminders"}
        elif act in {"create", "add", "new"}:
            if not title:
                return {"success": False, "error": "title is required to create a reminder"}
            script = f"""
            tell application "Reminders"
                tell list 1
                    make new reminder with properties {{name:"{title}"}}
                end tell
            end tell
            """
            ok, res = _run_osascript(script)
            return {"success": ok, "target": "reminders", "result": f"Added reminder: {title}" if ok else res}

    if t in {"mail", "email"}:
        if act in {"unread", "inbox", "read"}:
            script = """
            set output to ""
            tell application "Mail"
                set unreadMsgs to (every message of inbox whose read status is false)
                repeat with m in (items 1 through (count of unreadMsgs) of unreadMsgs)
                    set output to output & (sender of m) & ": " & (subject of m) & "\n"
                    if (count of lines of output) ≥ 5 then exit repeat
                end repeat
            end tell
            return output
            """
            ok, res = _run_osascript(script)
            return {"success": ok, "target": "mail", "unread": res or "No unread messages in Inbox"}
        elif act in {"draft", "create"}:
            script = f"""
            tell application "Mail"
                set newMsg to make new outgoing message with properties {{subject:"{subject}", content:"{body}", visible:true}}
                tell newMsg
                    make new to recipient at end of to recipients with properties {{address:"{to_recipient}"}}
                end tell
            end tell
            """
            ok, res = _run_osascript(script)
            return {"success": ok, "target": "mail", "result": "Draft created in Mail.app" if ok else res}

    if t in {"safari", "browser"}:
        script = """
        tell application "Safari"
            if (count of windows) > 0 then
                set currentTab to current tab of window 1
                return (name of currentTab) & " — " & (URL of currentTab)
            else
                return "Safari has no open windows"
            end if
        end tell
        """
        ok, res = _run_osascript(script)
        return {"success": ok, "target": "safari", "active_tab": res}

    if t in {"music", "audio", "spotify"}:
        if act in {"pause", "stop"}:
            _run_osascript('tell application "Music" to pause')
            return {"success": True, "target": "music", "state": "paused"}
        elif act in {"play", "resume"}:
            _run_osascript('tell application "Music" to play')
            return {"success": True, "target": "music", "state": "playing"}
        elif act in {"next", "skip"}:
            _run_osascript('tell application "Music" to next track')
            return {"success": True, "target": "music", "state": "skipped"}
        else:
            ok, res = _run_osascript('tell application "Music" to return (name of current track) & " by " & (artist of current track)')
            return {"success": ok, "target": "music", "now_playing": res or "No track playing"}

    return {"success": False, "error": f"Unknown target '{target}' or action '{action}'"}


def apple_shortcuts(action: str = "list", name: str = "", input_text: str = "") -> dict[str, Any]:
    """List or execute Apple Shortcuts via the macOS `shortcuts` CLI."""
    act = (action or "list").strip().lower()

    if act in {"list", "ls"}:
        try:
            proc = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=5.0)
            if proc.returncode == 0:
                shortcuts = [s.strip() for s in proc.stdout.splitlines() if s.strip()]
                return {"success": True, "count": len(shortcuts), "shortcuts": shortcuts}
            return {"success": False, "error": proc.stderr.strip()}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    if act in {"run", "execute"}:
        if not name:
            return {"success": False, "error": "name of the shortcut is required"}
        cmd = ["shortcuts", "run", name]
        if input_text:
            cmd.extend(["-i", input_text])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30.0)
            if proc.returncode == 0:
                return {"success": True, "name": name, "output": proc.stdout.strip()}
            return {"success": False, "name": name, "error": proc.stderr.strip() or f"exited with code {proc.returncode}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Shortcut '{name}' timed out after 30s"}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    return {"success": False, "error": f"Unknown action '{action}'"}


def spotlight_search(query: str, limit: int = 10, content_type: str = "") -> dict[str, Any]:
    """Instant desktop file search using macOS Spotlight (`mdfind`)."""
    q = (query or "").strip()
    if not q:
        return {"success": False, "error": "search query cannot be empty"}

    mdfind_query = q
    if content_type:
        mdfind_query = f"{q} && kMDItemContentType == '*{content_type}*'"

    try:
        proc = subprocess.run(
            ["mdfind", mdfind_query],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if proc.returncode == 0:
            lines = [p.strip() for p in proc.stdout.splitlines() if p.strip()]
            results = lines[:max(1, min(limit, 50))]
            return {
                "success": True,
                "total_matches": len(lines),
                "returned": len(results),
                "paths": results,
            }
        return {"success": False, "error": proc.stderr.strip()}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
