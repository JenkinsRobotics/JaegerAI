"""One log-line shape, everywhere.

The formatter is the thing every node, the supervisor and the chassis
render through, so a change to it changes every log in the ecosystem.
These pin the parts a reader (and a log parser) depends on: the field
order, the level tag, the ``kv`` column, and that colour stays off when
nobody is looking at a terminal.
"""

from __future__ import annotations

import re

from jaeger_os.app.logging import DEBUG_ENV, LogLine, debug_enabled, kv, log

LINE = re.compile(r"^\[\d\d:\d\d:\d\d\] \[(?P<src>[^\]]+)\] "
                  r"\[(?P<level>[A-Z]+)\]  (?P<msg>.*)$")


def _lines(capsys) -> list[str]:
    return capsys.readouterr().err.splitlines()


def test_shape_is_ts_source_level_message(capsys):
    log("whisper_stt", "audio session started")
    m = LINE.match(_lines(capsys)[0])
    assert m, "log line no longer matches [ts] [source] [LEVEL]  message"
    assert m["src"] == "whisper_stt"
    assert m["level"] == "INFO"
    assert m["msg"] == "audio session started"


def test_level_is_uppercased_not_validated(capsys):
    """An unknown level prints rather than raising — a log call must
    never be the thing that takes a node down."""
    log("n", "up", level="boot")
    log("n", "gone", level="wat")
    assert [LINE.match(x)["level"] for x in _lines(capsys)] == ["BOOT", "WAT"]


def test_kv_right_aligns_so_colons_form_a_column(capsys):
    kv("n", "node", "whisper_stt")
    kv("n", "version", "0.12.0")
    cols = [x.index(" : ") for x in _lines(capsys)]
    assert cols[0] == cols[1], "kv lost its column; boot banners will ragged"


def test_no_ansi_when_stderr_is_not_a_tty(capsys):
    """capsys stderr is not a terminal. If colour were decided once at
    import instead of per call, escape codes would leak into every
    captured log and every redirected file."""
    log("n", "plain", level="error")
    assert "\033[" not in _lines(capsys)[0]


def test_bus_mirror_publishes_one_logline(capsys):
    published = []
    log("n", "mirrored", level="warn",
        bus=type("B", (), {"publish": lambda self, m: published.append(m)})())
    assert len(published) == 1
    assert isinstance(published[0], LogLine)
    assert (published[0].source, published[0].level) == ("n", "warn")


def test_debug_is_silent_unless_asked(capsys, monkeypatch):
    """The whole reason a module can afford to narrate every action."""
    monkeypatch.delenv(DEBUG_ENV, raising=False)
    log("stt", "phrase 'hello' accepted", level="debug")
    log("stt", "phrase committed", level="info")
    assert [LINE.match(x)["level"] for x in _lines(capsys)] == ["INFO"]


def test_debug_can_be_narrowed_to_one_source(capsys, monkeypatch):
    """A global switch on a twelve-node robot buries the subsystem you
    are actually debugging."""
    monkeypatch.setenv(DEBUG_ENV, "stt, mic")
    log("stt", "wanted", level="debug")
    log("mic", "wanted too", level="debug")
    log("tts", "not wanted", level="debug")
    assert [LINE.match(x)["msg"] for x in _lines(capsys)] == [
        "wanted", "wanted too"]

    monkeypatch.setenv(DEBUG_ENV, "1")
    assert debug_enabled("anything at all")


def test_silenced_debug_costs_no_bus_publish(monkeypatch):
    """A trace nobody asked to see must not wake every /sys/log
    subscriber either."""
    monkeypatch.delenv(DEBUG_ENV, raising=False)
    published = []
    bus = type("B", (), {"publish": lambda self, m: published.append(m)})()
    log("stt", "quiet", level="debug", bus=bus)
    assert published == []


def test_a_broken_bus_does_not_break_the_log(capsys):
    class Exploding:
        def publish(self, msg):
            raise RuntimeError("bus is down")

    log("n", "still printed", bus=Exploding())
    assert LINE.match(_lines(capsys)[0])["msg"] == "still printed"
