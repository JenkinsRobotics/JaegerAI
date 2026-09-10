from __future__ import annotations

import json

import pytest

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.features.caldav import service

MULTISTATUS = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response><d:href>/cal/test.ics</d:href><d:propstat><d:prop>
    <d:getetag>"v1"</d:getetag><c:calendar-data>BEGIN:VCALENDAR
BEGIN:VEVENT
UID:test@jaeger
DTSTART:20260818T170000Z
DTEND:20260818T180000Z
SUMMARY:Planning
END:VEVENT
END:VCALENDAR</c:calendar-data>
  </d:prop></d:propstat></d:response>
</d:multistatus>"""


@pytest.fixture
def bound(tmp_path):
    layout = InstanceLayout(tmp_path / "instance")
    layout.ensure_dirs()
    service.bind(layout)
    service.configure(
        "work",
        calendar_url="https://calendar.example.test/cal",
        username="jaeger",
        password="secret",
    )
    return layout


def test_configuration_keeps_password_out_of_state(bound) -> None:
    persisted = json.loads(service._state_file("work", "config").read_text())
    assert "password" not in persisted
    assert persisted["secret_ref"] == "caldav.work.password"
    assert service._state_file("work", "config").stat().st_mode & 0o777 == 0o600
    with pytest.raises(service.CalDavError, match="requires HTTPS"):
        service.configure(
            "work",
            calendar_url="http://calendar.example.test/cal",
            username="jaeger",
            password="secret",
        )


def test_sync_and_put_are_protocol_bounded(bound) -> None:
    calls = []

    def transport(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "REPORT":
            return 207, {}, MULTISTATUS
        return 201, {"ETag": '"v2"'}, b""

    result = service.sync("work", transport=transport)
    assert result["events"][0]["uid"] == "test@jaeger"
    saved = service.put_event(
        "work",
        uid="planning@jaeger",
        summary="Planning",
        start="20260818T170000Z",
        end="20260818T180000Z",
        transport=transport,
    )
    assert saved["saved"]
    assert calls[-1][1]["headers"]["If-None-Match"] == "*"
    with pytest.raises(service.CalDavError, match="uid"):
        service.delete_event("work", uid="../secret", transport=transport)
