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


def test_profile_root_ignores_hermes_home_so_agent_home_never_self_links(tmp_path, monkeypatch):
    """HERMES_HOME names the WebUI *agent* home; the shared profile tree is a different dir.

    Honouring it made both the same path and ``profiles`` was linked to itself (ELOOP).
    """
    from jaeger_ai.core.runtime.profile_paths import hermes_profile_root

    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-webui-agent"))
    assert hermes_profile_root() == tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path.parent / "elsewhere"))
    assert hermes_profile_root() == tmp_path / "hermes"
