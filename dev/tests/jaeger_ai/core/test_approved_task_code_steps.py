"""Code steps inside an owner-approved task skip the per-step card; nothing else does."""
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.server import _GatewayToolConfirmationProvider


def _app(task):
    store = SimpleNamespace(get_task=lambda tid: task if task is not None and tid == "t1" else None)
    return SimpleNamespace(task_owner=SimpleNamespace(store=store))


def _req(op, force=False):
    return SimpleNamespace(operation=op, skill="code", force_prompt=force)


def _task(authorized=True, terminal=False):
    return SimpleNamespace(provenance={"authorized": authorized}, is_terminal=terminal)


@pytest.mark.parametrize("op", ["execute_code", "execute_with_tools"])
def test_code_step_in_approved_task_skips_card(op):
    p = _GatewayToolConfirmationProvider(_app(_task()), "task:t1", "t1:0")
    assert p._approved_task_code_step(_req(op)) is True


@pytest.mark.parametrize("sid,task,op", [
    ("chat-1", _task(), "execute_code"),                  # chat outside a task keeps the gate
    ("task:t1", _task(authorized=False), "execute_code"),  # unapproved task
    ("task:t1", _task(terminal=True), "execute_code"),     # finished task
    ("task:t2", _task(), "execute_code"),                 # unknown task
    ("task:t1", _task(), "write_file"),                   # not a code step
    ("task:t1", _task(), "terminal"),                     # shell is not a code step
])
def test_everything_else_keeps_the_gate(sid, task, op):
    p = _GatewayToolConfirmationProvider(_app(task), sid, "r")
    assert p._approved_task_code_step(_req(op)) is False


def test_confirm_returns_true_without_prompting(monkeypatch):
    p = _GatewayToolConfirmationProvider(_app(_task()), "task:t1", "t1:0")
    monkeypatch.setattr(p, "_session_grants", lambda: set())
    monkeypatch.setattr(p, "_prompt", lambda r: pytest.fail("prompted"))
    assert p.confirm(_req("execute_code")) is True


def test_policy_kernel_force_prompt_still_asks(monkeypatch):
    p = _GatewayToolConfirmationProvider(_app(_task()), "task:t1", "t1:0")
    asked = []
    monkeypatch.setattr(p, "_prompt", lambda r: asked.append(r) or False)
    monkeypatch.setattr(p, "_decided", lambda v: v)
    assert p.confirm(_req("execute_code", force=True)) is False and asked
