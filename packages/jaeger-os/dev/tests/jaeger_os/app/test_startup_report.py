"""What actually came up.

`--nodes`-style inventory shows what WOULD run; this shows what DID,
and they are not the same thing — a node can be declared, resolved,
started, and still fail its first tick.

Borrowed from Quantum Codex, where the startup block is the first
thing an operator reads. Ours had scattered log lines and a count.
"""

from __future__ import annotations

import pytest

from jaeger_os.app import JaegerApp

_BASE = '''
[app]
name = "report-test"
version = "1.2.3"
requires_framework = ">=0.1"
mode = "fused"
event_loop = "none"
config = ""
control = false

[bus]
backend = "inproc"
'''


def _app(tmp_path, extra=""):
    (tmp_path / "jaeger.toml").write_text(_BASE + extra)
    return JaegerApp(tmp_path / "jaeger.toml")


def test_the_header_names_the_app_and_its_transport(tmp_path):
    app = _app(tmp_path)
    try:
        app.boot()
        head = app.startup_report()[0]
        assert "report-test" in head and "1.2.3" in head
        assert "bus=inproc" in head
    finally:
        app.shutdown()


def test_a_running_node_is_reported_ok(tmp_path):
    app = _app(tmp_path, '''
[[node]]
id = "ticker"
backend = "thread"
factory = "dev.tests.jaeger_os.app.test_app_format:make_ticker"
''')
    try:
        app.boot()
        line = [l for l in app.startup_report() if "ticker" in l][0]
        assert "[OK]" in line or "[UP]" in line
        assert "test_app_format" in line, \
            "the report must say where the node came from"
    finally:
        app.shutdown()


def test_a_skipped_optional_node_says_WHY(tmp_path):
    """"[SKIP] tts" alone is useless — an operator who installed a
    voice needs to know the app looked and found nothing."""
    app = _app(tmp_path, '''
[[node]]
id = "voice"
slot = "test_missing_tts"
optional = true
''')
    try:
        app.boot()
        line = [l for l in app.startup_report() if "voice" in l][0]
        assert "[SKIP]" in line
        assert "test_missing_tts" in line, "the reason must name the slot"
    finally:
        app.shutdown()


def test_a_disabled_node_is_reported_not_hidden(tmp_path):
    app = _app(tmp_path, '''
[[node]]
id = "off"
backend = "thread"
factory = "dev.tests.jaeger_os.app.test_app_format:make_ticker"
enabled = false
''')
    try:
        app.boot()
        assert any("[SKIP]" in l and "off" in l for l in app.startup_report())
    finally:
        app.shutdown()


def test_surfaces_appear_too(tmp_path):
    """A window that failed to open is as interesting as a node that
    did — and it is what the operator is looking at."""
    app = _app(tmp_path, '''
[[surface]]
id = "console"
main = true
factory = "dev.tests.jaeger_os.app.test_app_format:make_ticker"
''')
    try:
        app.boot()
        assert any("console" in l and "surface" in l
                   for l in app.startup_report())
    finally:
        app.shutdown()


def test_the_report_is_returned_not_only_printed(tmp_path):
    """So a surface or a test can use it. A report that only exists as
    stdout cannot be shown in a GUI."""
    app = _app(tmp_path)
    try:
        app.boot()
        report = app.startup_report()
        assert isinstance(report, list) and all(isinstance(l, str)
                                                for l in report)
    finally:
        app.shutdown()
