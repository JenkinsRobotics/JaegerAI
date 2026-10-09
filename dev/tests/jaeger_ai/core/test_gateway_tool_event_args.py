"""Gateway tool.started events carry redacted, bounded arguments."""
from __future__ import annotations

import json

from jaeger_ai.core.gateway.server import _ARGS_TOTAL_MAX, _tool_event_args


def test_plain_args_cross_unchanged():
    assert _tool_event_args({"command": "git reset --hard abc123", "timeout": 30}) == {
        "command": "git reset --hard abc123", "timeout": 30}


def test_credential_keys_are_withheld_and_secret_shapes_masked():
    shown = _tool_event_args({"api_key": "plain-value", "headers": {"Authorization": "x"},
                              "command": "curl -H 'Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz123456' x"})
    assert shown["api_key"] == "<withheld>"
    assert shown["headers"]["Authorization"] == "<withheld>"
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in json.dumps(shown)


def test_long_values_are_clipped_and_total_is_bounded():
    shown = _tool_event_args({"path": "a.txt", "note": "x" * 10_000})
    assert shown["path"] == "a.txt" and len(shown["note"]) < 300
    many = _tool_event_args({f"k{i}": "y" * 200 for i in range(40)})
    assert len(json.dumps(many)) <= _ARGS_TOTAL_MAX


def test_non_dict_args_publish_nothing():
    assert _tool_event_args(None) == {} and _tool_event_args("raw") == {}


def test_payload_bodies_never_cross_only_their_size():
    shown = _tool_event_args({"path": "a.txt", "content": "FILE-BODY", "old_string": "A", "new_string": "B"})
    assert shown == {"path": "a.txt", "content": "<9 str>", "old_string": "<1 str>", "new_string": "<1 str>"}
