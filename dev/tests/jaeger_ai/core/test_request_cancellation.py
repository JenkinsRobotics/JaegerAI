"""R03 — request-scoped cancellation (RELEASE_AUDIT.md A01).

Unit contracts for the scope registry and the Gateway's effect-aware
settlement. The real in-flight path (HTTP → Gateway → EntityRuntime →
JaegerAgent → blocked provider) is covered by
``test_gateway_owned_process_contract.py``.
"""
from __future__ import annotations

import threading

import pytest

from jaeger_ai.core.runtime.cancellation import CancellationRegistry, bind_agent


class _Agent:
    def __init__(self):
        self.interrupts = 0
        self.signal = None

    def interrupt(self):
        self.interrupts += 1

    def bind_cancel_signal(self, signal):
        self.signal = signal


def test_cancel_before_any_agent_is_bound_is_preserved():
    registry = CancellationRegistry()
    registry.cancel("r1")  # races admission bookkeeping: no register yet
    agent = _Agent()

    bind_agent(registry.get("r1"), agent)

    assert agent.interrupts == 1
    assert agent.signal.is_set()


def test_cancel_interrupts_every_bound_agent_once_and_is_idempotent():
    registry = CancellationRegistry()
    scope = registry.register("r1")
    first, second = _Agent(), _Agent()
    bind_agent(scope, first)
    bind_agent(scope, second)

    assert scope.cancel() is True
    assert scope.cancel() is False

    assert (first.interrupts, second.interrupts) == (1, 1)


def test_scopes_are_independent_between_concurrent_requests():
    registry = CancellationRegistry()
    a, b = _Agent(), _Agent()
    bind_agent(registry.register("session-a-request"), a)
    bind_agent(registry.register("session-b-request"), b)

    registry.cancel("session-a-request")

    assert a.interrupts == 1 and b.interrupts == 0
    assert registry.is_cancelled("session-a-request")
    assert not registry.is_cancelled("session-b-request")


def test_cancel_from_another_thread_while_bound():
    registry = CancellationRegistry()
    agent = _Agent()
    bind_agent(registry.register("r1"), agent)
    worker = threading.Thread(target=registry.cancel, args=("r1",))
    worker.start()
    worker.join(timeout=5)
    assert agent.interrupts == 1


def test_release_forgets_the_scope_but_a_bound_agent_keeps_its_signal():
    registry = CancellationRegistry()
    agent = _Agent()
    scope = registry.register("r1")
    bind_agent(scope, agent)
    scope.cancel()
    registry.release("r1")
    assert registry.get("r1") is None
    assert agent.signal.is_set()


def test_bind_agent_without_scope_is_a_no_op():
    agent = _Agent()
    bind_agent(None, agent)
    assert agent.signal is None and agent.interrupts == 0


# ── Gateway settlement ───────────────────────────────────────────────


@pytest.fixture
def app(tmp_path):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    return JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))


def _admit(app, rid, *, native_session=None, run_id=None):
    admitted = app.store.admit_request("s", "work", request_id=rid)
    if run_id:
        app.store.bind_native(rid, native_run_id=run_id, native_session=native_session)
    return admitted


def test_settle_cancel_before_run_is_cancelled(app):
    admitted = _admit(app, "r1")
    assert app._settle_cancelled("s", admitted["turn_id"], "r1", {}) is True
    assert app.store.get_request("r1")["status"] == "cancelled"


@pytest.mark.parametrize("pending, expected", [(False, "cancelled"), (True, "execution_unknown")])
def test_settle_owner_run_consults_the_effect_ledger(app, monkeypatch, pending, expected):
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX

    monkeypatch.setattr(EntityRuntime, "run_has_indeterminate_effects", staticmethod(lambda run_id: pending))
    admitted = _admit(app, "r1", native_session=OWNER_RUN_SESSION_PREFIX + "s", run_id="run-1")

    assert app._settle_cancelled("s", admitted["turn_id"], "r1", {}) is True
    assert app.store.get_request("r1")["status"] == expected


def test_settle_leaves_legacy_mcp_runs_to_their_receipt(app):
    admitted = _admit(app, "r1", native_session="dispatcher", run_id="mcp-run")
    assert app._settle_cancelled("s", admitted["turn_id"], "r1", {}) is False
    assert app.store.get_request("r1")["status"] != "cancelled"
