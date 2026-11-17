"""Jaeger's own framework turn: the ``turn``/``reconciler`` pair that
:mod:`jaeger_ai.contract.frameworks` registers for the ``jaeger`` runtime.

``dispatcher_turn`` routes the message through the task dispatcher (so the
turn lands on the right native session) and then runs it with
:func:`~jaeger_ai.core.frameworks.native_runs.jaeger_turn`.
``jaeger_reconcile`` recovers a run after a restart.
"""
from __future__ import annotations

from .native_runs import jaeger_reconcile, jaeger_turn

__all__ = ["dispatcher_turn", "jaeger_reconcile"]


def dispatcher_turn(run, workspace=None):
    from jaeger_ai.features.dispatcher.store import DispatcherStore
    from jaeger_ai.interfaces.bridge_client import jaeger_bridge

    store = DispatcherStore(jaeger_bridge().layout)
    store.repair_projections()
    run.native_session = store.route(run.session, run.message)
    return jaeger_turn(run, workspace)
