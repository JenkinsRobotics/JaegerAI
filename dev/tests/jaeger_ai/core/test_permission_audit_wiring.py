"""The permission gate writes to the hash-chained audit log.

``AuditLogger`` (safety pillar 4 — the tamper-evident record of every gated
decision) shipped as a Phase-1 primitive whose own docstring said "wiring
(calls from the agent loop on every tier check) lands in a later chunk".
That chunk never landed: nothing imported the class, so every allow, deny
and confirmation prompt went unrecorded while the docs described an
append-only chain.

``PermissionPolicy.check()`` is the single point every gated decision passes
through, so the wiring lives there rather than scattered through the agent
loop. These tests pin both halves of the contract: every outcome is
recorded, and a failing audit sink can never change a permission decision.
"""

from __future__ import annotations

import pytest

from jaeger_os.core.safety.permissions import (
    AllowAllProvider,
    DenyAllProvider,
    HumanOverrideRequired,
    PermissionDenied,
    PermissionPolicy,
    PermissionRequest,
    PermissionTier,
    PolicyMode,
)
from jaeger_os.core.safety.safety_rules import AuditLogger


class _Spy:
    """Minimal stand-in recording the calls the gate makes."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def append(self, *, kind, request, outcome, detail=None):  # noqa: ANN001
        self.entries.append((kind, outcome))
        return "hash"


class _Broken:
    def append(self, **_kwargs):  # noqa: ANN003
        raise RuntimeError("audit sink is down")


def _req(tier: PermissionTier) -> PermissionRequest:
    return PermissionRequest(skill="demo", operation="run", tier=tier)


# ── every outcome is recorded ────────────────────────────────────────


def test_allow_is_recorded():
    spy = _Spy()
    PermissionPolicy(audit=spy).check(_req(PermissionTier.READ_ONLY))
    assert spy.entries == [("tier_check", "allow")]


def test_paused_denial_is_recorded():
    spy = _Spy()
    policy = PermissionPolicy(mode=PolicyMode.PAUSED, audit=spy)
    with pytest.raises(PermissionDenied):
        policy.check(_req(PermissionTier.READ_ONLY))
    assert spy.entries == [("tier_check", "deny_paused")]


def test_read_only_denial_is_recorded():
    spy = _Spy()
    policy = PermissionPolicy(mode=PolicyMode.READ_ONLY, audit=spy)
    with pytest.raises(PermissionDenied):
        policy.check(_req(PermissionTier.WRITE_LOCAL))
    assert spy.entries == [("tier_check", "deny_read_only")]


def test_dev_bypass_override_is_recorded():
    spy = _Spy()
    policy = PermissionPolicy(audit=spy)
    with pytest.raises(HumanOverrideRequired):
        policy.check(_req(PermissionTier.DEV_BYPASS))
    assert spy.entries == [("tier_check", "human_override_required")]


def test_confirmation_outcomes_are_recorded():
    approved, refused = _Spy(), _Spy()
    PermissionPolicy(confirmation=AllowAllProvider(), audit=approved).check(
        _req(PermissionTier.WRITE_LOCAL),
    )
    assert approved.entries == [("confirmation_prompt", "prompt_approved")]

    policy = PermissionPolicy(confirmation=DenyAllProvider(), audit=refused)
    with pytest.raises(PermissionDenied):
        policy.check(_req(PermissionTier.WRITE_LOCAL))
    assert refused.entries == [("confirmation_prompt", "prompt_refused")]


# ── auditing must never change the decision ──────────────────────────


def test_broken_audit_sink_does_not_break_an_allow():
    """Losing a log line beats failing an allowed action."""
    PermissionPolicy(audit=_Broken()).check(_req(PermissionTier.READ_ONLY))


def test_broken_audit_sink_still_denies():
    """A failing sink must not accidentally let a denial through."""
    policy = PermissionPolicy(mode=PolicyMode.PAUSED, audit=_Broken())
    with pytest.raises(PermissionDenied):
        policy.check(_req(PermissionTier.READ_ONLY))


def test_auditing_is_off_by_default():
    """No sink configured = historical behaviour, no new failure mode."""
    assert PermissionPolicy().audit is None
    PermissionPolicy().check(_req(PermissionTier.READ_ONLY))


# ── end to end against the real hash chain ───────────────────────────


def test_real_audit_logger_builds_a_verifiable_chain(tmp_path):
    """Two decisions through the real logger produce two chained entries."""
    log = tmp_path / "audit.log"
    policy = PermissionPolicy(
        confirmation=AllowAllProvider(), audit=AuditLogger(path=log),
    )
    policy.check(_req(PermissionTier.READ_ONLY))
    policy.check(_req(PermissionTier.WRITE_LOCAL))

    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2, lines
    assert policy.audit.prev_hash != "GENESIS"
