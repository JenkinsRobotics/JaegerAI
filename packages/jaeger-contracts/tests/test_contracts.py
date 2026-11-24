"""Contract & registry tests for jaeger-contracts."""

from __future__ import annotations

import pytest

from jaeger_contracts import (
    ActionProposal,
    DecisionKind,
    ModuleRegistry,
    PolicyVerdict,
)


class _DummyPolicy:
    def __init__(self, label: str, decision: DecisionKind) -> None:
        self._label = label
        self._decision = decision

    @property
    def name(self) -> str:
        return self._label

    def evaluate(self, proposal: ActionProposal, *, dry_run: bool = False) -> PolicyVerdict:
        return PolicyVerdict(decision=self._decision, policy_name=self._label)


def test_registry_enforces_protocol_and_hot_swaps() -> None:
    reg = ModuleRegistry()
    with pytest.raises(TypeError):
        reg.register("05-policy", "bad", object())

    reg.register("05-policy", "allow_all", _DummyPolicy("allow_all", DecisionKind.ALLOW))
    reg.register("05-policy", "deny_all", _DummyPolicy("deny_all", DecisionKind.DENY))

    assert reg.active_id("05-policy") == "allow_all"
    assert reg.get("05-policy").evaluate(ActionProposal("shell")).is_authorized is True

    reg.use("05-policy", "deny_all")
    assert reg.active_id("05-policy") == "deny_all"
    assert reg.get("05-policy").evaluate(ActionProposal("shell")).is_authorized is False
    assert reg.list_slot("05-policy") == ["allow_all", "deny_all"]


def test_registry_rejects_unknown_slot() -> None:
    reg = ModuleRegistry()
    with pytest.raises(KeyError):
        reg.register("99-unknown", "x", object())
