"""``jaeger sessions`` with no subcommand must list, not crash.

The bare parser defaults to ``run_list`` but only the ``list`` subparser
defines ``--profile``/``--limit``, so ``args.profile`` was missing."""

from __future__ import annotations

import argparse

from jaeger_ai.cli import sessions_cmd


def test_bare_sessions_lists_without_profile_attribute(monkeypatch, capsys):
    monkeypatch.setattr(sessions_cmd, "by_profile", lambda: {})
    monkeypatch.setattr(sessions_cmd, "all_sessions", lambda: [])
    monkeypatch.setattr(sessions_cmd, "endpoints", lambda: [])

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    sessions_cmd.register(sub)
    args = parser.parse_args(["sessions"])

    assert args._handler(args) in (0, None)
    assert "conversations across" in capsys.readouterr().out
