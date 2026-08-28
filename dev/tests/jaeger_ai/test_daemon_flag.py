"""``jaeger --daemon`` routes to the headless daemon.

``run_daemon`` was complete but unreachable — nothing in the CLI referenced
it, so its docstring ("Intended to run under launchd") described a path that
could not be taken. These tests pin the wiring, and that the flag is peeled
before argparse like its siblings (``--stream`` / ``--voice`` / ``--tui``),
which never reach ``parse_args``.
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest


@pytest.fixture()
def dispatch():
    from jaeger_ai.main import _main_dispatch

    return _main_dispatch


def _argv(*args):
    return mock.patch.object(sys, "argv", ["jaeger", *args])


def test_daemon_flag_calls_run_daemon(dispatch):
    with _argv("--daemon"), \
         mock.patch("jaeger_ai.main.run_daemon", return_value=0) as rd:
        assert dispatch() == 0
    rd.assert_called_once_with(instance_name=None, poll_seconds=60)


def test_daemon_forwards_instance(dispatch):
    with _argv("--daemon", "--instance", "ares"), \
         mock.patch("jaeger_ai.main.run_daemon", return_value=0) as rd:
        dispatch()
    rd.assert_called_once_with(instance_name="ares", poll_seconds=60)


def test_daemon_forwards_poll_seconds(dispatch):
    with _argv("--daemon", "--poll-seconds", "15"), \
         mock.patch("jaeger_ai.main.run_daemon", return_value=0) as rd:
        dispatch()
    rd.assert_called_once_with(instance_name=None, poll_seconds=15)


def test_poll_seconds_has_a_floor(dispatch):
    """A 0/negative poll would spin the loop hot under launchd."""
    with _argv("--daemon", "--poll-seconds", "0"), \
         mock.patch("jaeger_ai.main.run_daemon", return_value=0) as rd:
        dispatch()
    assert rd.call_args.kwargs["poll_seconds"] == 5


def test_bad_poll_seconds_falls_back_without_crashing(dispatch):
    with _argv("--daemon", "--poll-seconds", "soon"), \
         mock.patch("jaeger_ai.main.run_daemon", return_value=0) as rd:
        assert dispatch() == 0
    assert rd.call_args.kwargs["poll_seconds"] == 60


def test_instance_without_a_value_is_misuse(dispatch):
    with _argv("--daemon", "--instance"), \
         mock.patch("jaeger_ai.main.run_daemon") as rd:
        assert dispatch() == 2
    rd.assert_not_called()


def test_daemon_flag_is_consumed_before_argparse(dispatch):
    """It must not survive into sys.argv — parse_args would reject it."""
    seen: list[list[str]] = []

    def _capture(**kw):
        seen.append(list(sys.argv))
        return 0

    with _argv("--daemon"), mock.patch("jaeger_ai.main.run_daemon", _capture):
        dispatch()
    assert "--daemon" not in seen[0]


def test_daemon_returns_run_daemon_exit_code(dispatch):
    with _argv("--daemon"), mock.patch("jaeger_ai.main.run_daemon", return_value=3):
        assert dispatch() == 3


def test_without_the_flag_run_daemon_is_not_called(dispatch):
    """A bare `jaeger` keeps booting the interactive path unchanged."""
    with _argv("--doctor"), \
         mock.patch("jaeger_ai.main.run_daemon") as rd, \
         mock.patch("jaeger_ai.main.parse_args", side_effect=SystemExit(0)):
        with pytest.raises(SystemExit):
            dispatch()
    rd.assert_not_called()
