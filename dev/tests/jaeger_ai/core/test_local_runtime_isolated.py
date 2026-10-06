"""The in-process agent turn is not a production path.

A Jaeger turn that did not come through the Gateway would be a second Jaeger with
its own model, memory writes and task state, so the local executors fail closed
unless the operator re-enabled the isolated paths.
"""
from __future__ import annotations

import pytest

from jaeger_ai import main
from jaeger_ai.contract.legacy_paths import LegacyPathDisabled, require_legacy_path


@pytest.fixture(autouse=True)
def _production_environment(monkeypatch):
    monkeypatch.delenv("JAEGER_LEGACY_PATHS", raising=False)


def test_require_legacy_path_fails_closed_by_default(monkeypatch):
    with pytest.raises(LegacyPathDisabled, match="Gateway"):
        require_legacy_path("In-process agent turn")
    monkeypatch.setenv("JAEGER_LEGACY_PATHS", "1")
    require_legacy_path("In-process agent turn")


@pytest.mark.parametrize("call", [
    lambda: main.run_for_voice(object(), "hello", session_key="s"),
    lambda: main._run_turn(object(), "hello", session_key="s"),
])
def test_the_in_process_turn_refuses_to_run_without_the_switch(call):
    with pytest.raises(LegacyPathDisabled):
        call()
