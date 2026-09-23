"""F03 / A04 — a turn's approval policy must not leak process-wide.

``EntityRuntime.run_subordinate_react`` receives a confirmation provider
bound to one session and request (the Gateway parks that request's tool
approvals). It used to ``install_policy`` it, which also writes JaegerOS's
process-wide fallback: after the turn — or while another session's turn is
running — any thread without the ContextVar resolved to *that* request's
provider, so an approval could be parked (or cancelled) under a foreign
request. The turn's policy is now scoped to the turn's own context.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from jaeger_os.core.safety import permissions


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    from jaeger_ai.core.entity import runtime as runtime_module
    from jaeger_ai.core.instance import schemas
    from jaeger_ai.core.models import external_model
    from jaeger_agent.cognition import executive, sqlite_commitments, sqlite_runs
    from jaeger_agent.loop import runtime_bridge
    from jaeger_agent.memory import sqlite_store

    seen: dict[str, object] = {}

    class _Executive:
        def __init__(self, agent, *args, **kwargs):
            self.agent = agent

        def ensure_run(self):
            return SimpleNamespace(id="run-1")

        def run_turn(self, prompt):
            seen["turn_thread"] = permissions.current_policy()
            holder = {}
            probe = threading.Thread(target=lambda: holder.update(policy=permissions.current_policy()))
            probe.start()
            probe.join()
            seen["contextless_thread"] = holder["policy"]
            return "ok"

    monkeypatch.setattr(sqlite_store, "bind", lambda layout: None)
    monkeypatch.setattr(schemas, "load_yaml", lambda path, model: SimpleNamespace(
        external_model=SimpleNamespace(provider="scripted")))
    monkeypatch.setattr(external_model, "ExternalModelClient",
                        lambda ext, layout: SimpleNamespace(provider="scripted", model_name="m"))
    monkeypatch.setattr(runtime_bridge, "build_jaeger_agent",
                        lambda client, **kw: SimpleNamespace(bind_run=lambda run_id: None,
                                                             interrupt=lambda: None))
    monkeypatch.setattr(executive, "TurnExecutive", _Executive)
    monkeypatch.setattr(sqlite_runs, "SqliteRunStore", lambda: None)
    monkeypatch.setattr(sqlite_commitments, "SqliteCommitmentStore", lambda: None)

    rt = runtime_module.EntityRuntime.__new__(runtime_module.EntityRuntime)
    rt.layout = SimpleNamespace(root=tmp_path, config_path=tmp_path / "config.yaml")
    return rt, seen


class _Provider:
    def __init__(self, name):
        self.name = name

    def confirm(self, request):  # pragma: no cover - identity only
        return False


def test_turn_policy_is_visible_to_the_turn_but_not_installed_process_wide(runtime, monkeypatch):
    rt, seen = runtime
    boot_policy = permissions.PermissionPolicy()
    monkeypatch.setattr(permissions, "_installed_policy", boot_policy)
    provider = _Provider("request-A")

    rt.run_subordinate_react("hi", session_key="A", request_id="A-1",
                             confirmation_provider=provider)

    assert seen["turn_thread"].confirmation is provider
    assert seen["contextless_thread"] is boot_policy, (
        "a thread outside this turn's context must not see the turn's provider"
    )
    assert permissions._installed_policy is boot_policy
    assert permissions.current_policy().confirmation is not provider


def test_concurrent_turns_each_see_only_their_own_provider(runtime, monkeypatch):
    rt, _ = runtime
    monkeypatch.setattr(permissions, "_installed_policy", None)
    from jaeger_agent.cognition import executive

    barrier = threading.Barrier(2)
    observed: dict[str, object] = {}

    class _Both(executive.TurnExecutive):  # type: ignore[misc, valid-type]
        def run_turn(self, prompt):
            barrier.wait(timeout=5)  # both turns are active at once
            observed[prompt] = permissions.current_policy().confirmation
            barrier.wait(timeout=5)
            return "ok"

    monkeypatch.setattr(executive, "TurnExecutive", _Both)
    providers = {"A": _Provider("A"), "B": _Provider("B")}
    threads = [threading.Thread(target=rt.run_subordinate_react, args=(key,),
                                kwargs={"session_key": key, "request_id": key,
                                        "confirmation_provider": providers[key]})
               for key in providers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert observed == providers
