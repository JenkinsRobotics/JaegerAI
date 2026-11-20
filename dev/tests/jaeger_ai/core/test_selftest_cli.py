"""Unit tests for ``jaeger selftest`` CLI routing, report formatting, and audio/model helpers."""
from __future__ import annotations

import sys

from jaeger_ai.cli.entry import _route
from jaeger_ai.core.selftest.audio_hil import MAX_SAFE_GAIN, word_match_score
from jaeger_ai.core.selftest.models import CheckResult, CheckStatus, SelftestReport


def test_cli_routes_selftest_subcommand():
    argv = _route(["selftest", "--full", "--audio", "--json"], sys.executable)
    assert argv == [sys.executable, "-m", "jaeger_ai.core.selftest.runner", "--full", "--audio", "--json"]


def test_selftest_report_exit_codes_and_serialization():
    ok_rep = SelftestReport(
        commit="abc1234",
        started_at="2026-11-19T20:00:00Z",
        finished_at="2026-11-19T20:01:00Z",
        checks=[
            CheckResult(id="c1", name="One", status=CheckStatus.PASS, required=True),
            CheckResult(id="c2", name="Two", status=CheckStatus.BLOCKED, required=False, reason="optional hw"),
        ],
    )
    assert ok_rep.overall_status == "PASS"
    assert ok_rep.exit_code == 0
    assert "PASS=1" in ok_rep.to_human_report()

    fail_rep = SelftestReport(
        commit="abc1234",
        started_at="2026-11-19T20:00:00Z",
        finished_at="2026-11-19T20:01:00Z",
        checks=[CheckResult(id="c1", name="One", status=CheckStatus.FAIL, required=True, reason="broken")],
    )
    assert fail_rep.overall_status == "FAIL"
    assert fail_rep.exit_code == 1


def test_word_match_and_volume_safety():
    assert word_match_score("Truth acoustic check alpha 74.", "truth acoustic check alpha 74") == 1.0
    assert word_match_score("alpha beta gamma", "alpha delta") < 0.5
    assert MAX_SAFE_GAIN <= 0.6
