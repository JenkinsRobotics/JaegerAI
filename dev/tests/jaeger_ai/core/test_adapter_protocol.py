"""Unit tests for adapter_protocol ported from donor patterns."""
import pytest

from jaeger_ai.core.frameworks.adapter_protocol import (
    strip_kaomoji,
    clean_transcript_text,
    is_benign_stderr,
    reclassify_log_stream,
    parse_tool_line,
    SessionCodec,
)


def test_strip_kaomoji():
    assert strip_kaomoji("Hello (^_^) world!") == "Hello world!"
    assert strip_kaomoji("(╯°□°)╯︵ ┻━┻ flip table") == "flip table"
    assert strip_kaomoji("Normal (parenthetical) note") == "Normal (parenthetical) note"


def test_clean_transcript_text():
    raw = "\x1b[32m[INFO]\x1b[0m +-----------------+\n| Result: success |\n+-----------------+\n(◕‿◕) Done!"
    cleaned = clean_transcript_text(raw)
    assert "[INFO]" in cleaned
    assert "Result: success" in cleaned
    assert "+-----------------+" not in cleaned
    assert "(◕‿◕)" not in cleaned
    assert "Done!" in cleaned


def test_is_benign_stderr():
    assert is_benign_stderr("DeprecationWarning: pkg_resources is deprecated")
    assert is_benign_stderr("2026-09-22 10:00:00 [INFO] mcp server listening on port 8000")
    assert is_benign_stderr("INFO:     Started server process [12345]")
    assert is_benign_stderr("HTTP/1.1 200 OK")
    assert is_benign_stderr("")

    # Real errors must not be benign
    assert not is_benign_stderr("Traceback (most recent call last):\n  File 'main.py', line 1\nZeroDivisionError: division by zero")
    assert not is_benign_stderr("FATAL: database connection refused")
    assert not is_benign_stderr("RuntimeError: Tool failed")


def test_reclassify_log_stream():
    chunk = "2026-09-22 10:00:00 [INFO] Initializing service"
    stream, text = reclassify_log_stream("stderr", chunk)
    assert stream == "stdout"
    assert text == chunk

    err_chunk = "Traceback (most recent call last):\nKeyError: 'user'"
    err_stream, _ = reclassify_log_stream("stderr", err_chunk)
    assert err_stream == "stderr"


def test_parse_tool_line():
    line1 = "[TOOL] bash(command='ls -la')"
    parsed1 = parse_tool_line(line1)
    assert parsed1 is not None
    assert parsed1["name"] == "bash"
    assert parsed1["phase"] == "start"

    line2 = "[TOOL_DONE] bash status=completed 0.42s"
    parsed2 = parse_tool_line(line2)
    assert parsed2 is not None
    assert parsed2["phase"] == "done"
    assert parsed2["name"] == "bash"
    assert parsed2["duration"] == "0.42s"

    line3 = "Regular assistant prose message without tools."
    assert parse_tool_line(line3) is None


def test_session_codec():
    raw = {"sessionId": "sess-abc-xyz", "extra": "data"}
    serialized = SessionCodec.serialize(raw)
    assert serialized == {"session_id": "sess-abc-xyz"}

    deserialized = SessionCodec.deserialize(serialized)
    assert deserialized == {"session_id": "sess-abc-xyz"}

    assert SessionCodec.get_display_id(raw) == "sess-abc-xyz"
    assert SessionCodec.get_display_id(None) is None

    # Normalization
    assert SessionCodec.normalize_session_id("roundtable-hermes:uuid-123") == "uuid-123"
    assert SessionCodec.normalize_session_id("uuid-456") == "uuid-456"
