"""Pure wire-contract & SPI protocol tests for jaeger-contracts."""

from __future__ import annotations

import json

from jaeger_contracts import (
    WIRE_SCHEMA_VERSION,
    ActionProposal,
    DecisionKind,
    OperationClass,
    PolicyPort,
    PolicyVerdict,
    WireActionReceipt,
    WireEnvelope,
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


def test_wire_envelope_roundtrip_is_pure_json() -> None:
    env = WireEnvelope(
        envelope_id="env-1",
        event_type="turn.completed",
        session_id="sess-1",
        seq=7,
        timestamp_ms=1700000000000,
        payload={"ok": True},
        trace_id="trace-abc",
        idempotency_key="idem-1",
    )
    encoded = json.dumps(env.to_dict())
    decoded = WireEnvelope.from_dict(json.loads(encoded))
    assert decoded == env
    assert decoded.schema_version == WIRE_SCHEMA_VERSION


def test_operation_class_enforces_fail_closed_mutation_retries() -> None:
    ro = WireActionReceipt("r1", "list_mail", OperationClass.READ_ONLY, "failed", 1000)
    mut_unknown = WireActionReceipt("r2", "send_email", OperationClass.NON_IDEMPOTENT_MUTATION, "outcome_unknown", 1000)
    mut_failed = WireActionReceipt("r3", "move_mail", OperationClass.NON_IDEMPOTENT_MUTATION, "failed", 1000)
    idem_unknown = WireActionReceipt("r4", "set_label", OperationClass.IDEMPOTENT_MUTATION if hasattr(OperationClass, "IDEMPOTENT_MUTATION") else OperationClass.IDEMPOTENT_WRITE, "outcome_unknown", 1000)
    assert ro.safe_to_retry is True
    assert mut_unknown.safe_to_retry is False
    assert mut_failed.safe_to_retry is False
    assert idem_unknown.safe_to_retry is True


def test_policy_protocol_conformance() -> None:
    p = _DummyPolicy("allow_all", DecisionKind.ALLOW)
    assert isinstance(p, PolicyPort)
    assert p.evaluate(ActionProposal("shell")).is_authorized is True
