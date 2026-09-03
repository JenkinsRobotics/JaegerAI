"""Instance-scoped CalDAV configuration, synchronization, and event writes.

Jaeger owns calendar metadata and its bounded offline cache. Credentials use
Jaeger's permission-checked instance credential store; configuration files
only persist a secret reference.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from base64 import b64encode
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from jaeger_agent.credentials import get_credential, set_credential

from jaeger_ai.core.instance.instance import InstanceLayout

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 15
SECRET_KEY = "caldav.password"
_SAFE_UID = re.compile(r"^[A-Za-z0-9._@-]{1,255}$")
_LAYOUT: InstanceLayout | None = None


class CalDavError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def bind(layout: InstanceLayout) -> None:
    """Bind CalDAV state and secrets to a concrete Jaeger instance."""
    global _LAYOUT
    _LAYOUT = layout


def _layout() -> InstanceLayout:
    if _LAYOUT is None:
        raise CalDavError("CalDAV is not bound to a Jaeger instance", 503)
    return _LAYOUT


def _state_file(profile: str | None, name: str) -> Path:
    safe_profile = (profile or "default").replace("/", "_").replace("\\", "_")
    return _layout().memory_dir / "caldav" / safe_profile / f"{name}.json"


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f"{path.stem}-", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _validate_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CalDavError("calendar_url must be an absolute HTTP(S) URL", 400)
    if parsed.username or parsed.password or parsed.fragment:
        raise CalDavError(
            "calendar_url must not contain credentials or a fragment", 400
        )
    if parsed.scheme == "http" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise CalDavError("CalDAV requires HTTPS except for loopback test servers", 400)
    return parsed.geturl().rstrip("/") + "/"


def get_config(profile: str | None) -> dict[str, Any]:
    config = _read_json(_state_file(profile, "config"), {})
    if not isinstance(config, dict):
        config = {}
    return {
        "configured": bool(config.get("calendar_url") and config.get("username")),
        "calendar_url": config.get("calendar_url"),
        "username": config.get("username"),
        "credential_provider": "os_keychain",
        "secret_ref": config.get("secret_ref") if config else None,
        "updated_at": config.get("updated_at"),
    }


def configure(
    profile: str | None, *, calendar_url: str, username: str, password: str | None
) -> dict[str, Any]:
    url = _validate_url(calendar_url)
    user = str(username or "").strip()
    if not user:
        raise CalDavError("username is required", 400)
    prior = get_config(profile)
    if password:
        credential_name = f"caldav.{(profile or 'default').replace('/', '_')}.password"
        set_credential(_layout(), credential_name, password)
    elif not prior["configured"]:
        raise CalDavError("password is required for initial configuration", 400)
    value = {
        "calendar_url": url,
        "username": user,
        "secret_ref": f"caldav.{(profile or 'default').replace('/', '_')}.password",
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _atomic_json(_state_file(profile, "config"), value)
    return get_config(profile)


def _credentials(profile: str | None) -> tuple[dict[str, Any], str]:
    config = get_config(profile)
    if not config["configured"]:
        raise CalDavError("CalDAV is not configured", 409)
    return config, get_credential(_layout(), str(config["secret_ref"]))


def _request(
    method: str,
    url: str,
    *,
    username: str,
    password: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    authorization = b64encode(f"{username}:{password}".encode()).decode("ascii")
    request = Request(url, data=body, method=method)
    request.add_header("Authorization", f"Basic {authorization}")
    request.add_header("User-Agent", "JaegerAI-CalDAV/1")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise CalDavError("CalDAV response exceeded the 8 MiB limit")
            return int(response.status), dict(response.headers.items()), payload
    except HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace").strip()
        raise CalDavError(
            f"CalDAV returned HTTP {exc.code}: {detail or exc.reason}", 502
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise CalDavError(f"CalDAV connection failed: {exc}", 502) from exc


def _unfold_ics(value: str) -> list[str]:
    lines: list[str] = []
    for line in value.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _ics_value(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def parse_event(
    ics: str, *, href: str = "", etag: str | None = None
) -> dict[str, Any] | None:
    inside = False
    fields: dict[str, str] = {}
    for line in _unfold_ics(ics):
        if line == "BEGIN:VEVENT":
            inside = True
            continue
        if line == "END:VEVENT":
            break
        if not inside or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        fields[key.split(";", 1)[0].upper()] = _ics_value(raw)
    uid = fields.get("UID")
    if not uid:
        return None
    return {
        "uid": uid,
        "summary": fields.get("SUMMARY", "Untitled event"),
        "description": fields.get("DESCRIPTION", ""),
        "start": fields.get("DTSTART"),
        "end": fields.get("DTEND"),
        "href": href,
        "etag": etag,
    }


def _events_from_multistatus(payload: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise CalDavError("CalDAV returned invalid XML") from exc
    events = []
    for response in root.findall("{DAV:}response"):
        href = response.findtext("{DAV:}href") or ""
        etag = response.findtext(".//{DAV:}getetag")
        calendar_data = response.findtext(
            ".//{urn:ietf:params:xml:ns:caldav}calendar-data"
        )
        event = parse_event(calendar_data or "", href=href, etag=etag)
        if event:
            events.append(event)
    return events


def list_cached_events(profile: str | None) -> dict[str, Any]:
    value = _read_json(_state_file(profile, "cache"), {"events": [], "synced_at": None})
    return value if isinstance(value, dict) else {"events": [], "synced_at": None}


def sync(
    profile: str | None,
    transport: Callable[..., tuple[int, dict[str, str], bytes]] = _request,
) -> dict[str, Any]:
    config, password = _credentials(profile)
    body = b"""<?xml version=\"1.0\" encoding=\"utf-8\"?><c:calendar-query xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name=\"VCALENDAR\"><c:comp-filter name=\"VEVENT\"/></c:comp-filter></c:filter></c:calendar-query>"""
    _, _, payload = transport(
        "REPORT",
        config["calendar_url"],
        username=config["username"],
        password=password,
        body=body,
        headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
    )
    value = {
        "events": _events_from_multistatus(payload),
        "synced_at": datetime.now(UTC).isoformat(),
    }
    _atomic_json(_state_file(profile, "cache"), value)
    return value


def _escape_ics(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def put_event(
    profile: str | None,
    *,
    uid: str | None,
    summary: str,
    start: str,
    end: str,
    description: str = "",
    etag: str | None = None,
    transport: Callable[..., tuple[int, dict[str, str], bytes]] = _request,
) -> dict[str, Any]:
    config, password = _credentials(profile)
    event_uid = uid or f"{uuid.uuid4().hex}@jaeger"
    if not _SAFE_UID.fullmatch(event_uid):
        raise CalDavError("uid contains unsupported characters", 400)
    if not summary.strip() or not start.strip() or not end.strip():
        raise CalDavError("summary, start, and end are required", 400)
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//JaegerAI//Work Management//EN",
            "BEGIN:VEVENT",
            f"UID:{event_uid}",
            f"DTSTAMP:{now}",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            f"SUMMARY:{_escape_ics(summary)}",
            f"DESCRIPTION:{_escape_ics(description)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    ).encode()
    headers = {
        "Content-Type": "text/calendar; charset=utf-8",
        "If-Match" if etag else "If-None-Match": etag or "*",
    }
    href = config["calendar_url"] + quote(event_uid, safe="@._-") + ".ics"
    _, response_headers, _ = transport(
        "PUT",
        href,
        username=config["username"],
        password=password,
        body=ics,
        headers=headers,
    )
    return {
        "uid": event_uid,
        "href": href,
        "etag": response_headers.get("ETag"),
        "saved": True,
    }


def delete_event(
    profile: str | None,
    *,
    uid: str,
    etag: str | None = None,
    transport: Callable[..., tuple[int, dict[str, str], bytes]] = _request,
) -> dict[str, Any]:
    config, password = _credentials(profile)
    if not _SAFE_UID.fullmatch(uid):
        raise CalDavError("uid contains unsupported characters", 400)
    href = config["calendar_url"] + quote(uid, safe="@._-") + ".ics"
    headers = {"If-Match": etag} if etag else {}
    transport(
        "DELETE", href, username=config["username"], password=password, headers=headers
    )
    return {"uid": uid, "deleted": True}
