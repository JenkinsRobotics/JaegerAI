"""Autonomy defaults (Constitution invariant 11, Phase 1 workstream 2).

The default is ``scoped``, not ``auto``. ``auto`` is honored only when the
owner saved it explicitly. An unreadable or invalid config never widens
autonomy: it reads as ``ask``.
"""
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


def test_the_default_is_scoped_not_auto():
    assert autonomy.CONFIG_DEFAULT == "scoped"
    assert autonomy.UNREADABLE_DEFAULT == "ask"
    assert AutomationConfig().autonomy == "scoped"


def test_the_saved_setting_is_read_and_a_bad_one_fails_closed(tmp_path):
    good = tmp_path / "good.yaml"
    good.write_text("automation:\n  autonomy: ask\n")
    assert autonomy.configured_autonomy(good) == "ask"
    explicit_auto = tmp_path / "auto.yaml"
    explicit_auto.write_text("automation:\n  autonomy: auto\n")
    assert autonomy.configured_autonomy(explicit_auto) == "auto"
    bad = tmp_path / "bad.yaml"
    bad.write_text("automation:\n  autonomy: reckless\n")
    assert autonomy.configured_autonomy(bad) == "ask"
    corrupt = tmp_path / "corrupt.yaml"
    corrupt.write_text("automation: [unclosed\n")
    assert autonomy.configured_autonomy(corrupt) == "ask"
    not_mapping = tmp_path / "list.yaml"
    not_mapping.write_text("- a\n- b\n")
    assert autonomy.configured_autonomy(not_mapping) == "ask"
    unset = tmp_path / "unset.yaml"
    unset.write_text("automation:\n  inner_max_iterations: 10\n")
    assert autonomy.configured_autonomy(unset) == "scoped"
    assert autonomy.configured_autonomy(tmp_path / "missing.yaml") == "scoped"
    assert autonomy.configured_autonomy(None) == "scoped"


def test_an_unreadable_config_file_reads_as_ask(tmp_path):
    unreadable = tmp_path / "locked.yaml"
    unreadable.write_text("automation:\n  autonomy: auto\n")
    unreadable.chmod(0)
    try:
        assert autonomy.configured_autonomy(unreadable) == "ask"
    finally:
        unreadable.chmod(0o600)


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


def test_the_gateway_does_not_auto_approve_by_default(tmp_path, monkeypatch):
    # No saved setting → scoped → a privileged call must be asked, and with no
    # running loop to park an approval the provider fails closed.
    provider = _provider(tmp_path, monkeypatch, None)
    assert provider.confirm(REQUEST) is False


def test_an_explicit_saved_auto_is_still_honored(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, "automation:\n  autonomy: auto\n")
    assert provider.confirm(REQUEST) is True


def test_a_corrupt_config_never_auto_approves(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, "automation: [unclosed\n")
    assert provider.confirm(REQUEST) is False


def test_policy_kernel_approval_ignores_auto_and_grants(tmp_path, monkeypatch):
    """REQUIRE_APPROVAL from PolicyKernel (force_prompt) is answered only by an
    explicit decision, even with autonomy auto saved."""
    provider = _provider(tmp_path, monkeypatch, "automation:\n  autonomy: auto\n")
    forced = SimpleNamespace(skill="policy:terminal", operation="terminal",
                             tier=PermissionTier.PRIVILEGED, summary="x", force_prompt=True)
    assert provider.confirm(forced) is False  # no loop to ask on → refused


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
