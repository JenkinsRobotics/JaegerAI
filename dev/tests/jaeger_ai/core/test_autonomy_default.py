"""Full access by default: it is the operator's own assistant on their own machine."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.gateway.server import JaegerGatewayApp, _GatewayToolConfirmationProvider
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.instance.schemas import AutomationConfig
from jaeger_ai.core.runtime import autonomy
from jaeger_os.core.safety.permissions import PermissionTier


@pytest.fixture(autouse=True)
def clean_state():
    before = dict(autonomy._state)
    autonomy._state.update({"mode": autonomy.DEFAULT, "explicit": False})
    yield
    autonomy._state.clear()
    autonomy._state.update(before)


def test_the_saved_default_is_full_access():
    assert autonomy.CONFIG_DEFAULT == "auto"
    assert AutomationConfig().autonomy == "auto"


def test_the_saved_setting_is_read_and_a_bad_one_falls_back(tmp_path):
    good = tmp_path / "good.yaml"
    good.write_text("automation:\n  autonomy: ask\n")
    assert autonomy.configured_autonomy(good) == "ask"
    bad = tmp_path / "bad.yaml"
    bad.write_text("automation:\n  autonomy: reckless\n")
    assert autonomy.configured_autonomy(bad) == autonomy.CONFIG_DEFAULT
    assert autonomy.configured_autonomy(tmp_path / "missing.yaml") == autonomy.CONFIG_DEFAULT
    assert autonomy.configured_autonomy(None) == autonomy.CONFIG_DEFAULT


def test_an_explicit_switch_beats_the_saved_setting(tmp_path):
    saved = tmp_path / "c.yaml"
    saved.write_text("automation:\n  autonomy: ask\n")
    assert autonomy.effective_autonomy(saved) == "ask"
    autonomy.set_autonomy("auto")
    assert autonomy.effective_autonomy(saved) == "auto"


def _provider(tmp_path, monkeypatch, config_text: str | None, *, running_loop=False):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "g.sqlite3"))
    config = tmp_path / "config.yaml"
    if config_text is not None:
        config.write_text(config_text)
    layout = SimpleNamespace(config_path=config, root=tmp_path)
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: SimpleNamespace(layout=layout)))
    return _GatewayToolConfirmationProvider(app, "s", "r")


REQUEST = SimpleNamespace(skill="shell", operation="run_shell", tier=PermissionTier.PRIVILEGED, summary="x")


def test_the_gateway_approves_without_prompting_by_default(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, None)
    assert provider.confirm(REQUEST) is True
    assert provider.app.store.list_approvals() == [] if hasattr(provider.app.store, "list_approvals") else True


def test_ask_mode_still_refuses_without_a_way_to_prompt(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, "automation:\n  autonomy: ask\n")
    # No event loop is running in this unit test, so a parked approval cannot be
    # answered: the provider must fail closed, not approve.
    assert provider.confirm(REQUEST) is False


def test_hardline_commands_are_refused_even_at_full_access(tmp_path):
    from jaeger_agent.tools.code import run_shell
    from jaeger_agent.core.workspace import DefaultWorkspace, bind
    from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy

    bind(DefaultWorkspace(tmp_path / "agent").create())
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        out = run_shell(command="rm -rf /")
    assert out["hardline_blocked"] is True
