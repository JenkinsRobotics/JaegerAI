"""GB-031 / GB-027: dry-run preview, versioned team/local review rules, app grants."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from jaeger_ai.core.authority import kernel as K
from jaeger_ai.core.authority.kernel import (
    AuthorityDecisionType, PolicyKernel, ProposedAction, ReviewRule, ReviewRuleStore, StaleRuleRevision,
)


@pytest.fixture
def iso(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JAEGER_GLOBAL_STOP_PATH", str(tmp_path / "ctl" / "global-stop.json"))
    monkeypatch.setenv("JAEGER_LIFECYCLE_LEASE", str(tmp_path / "ctl" / "lease.json"))
    inst = tmp_path / "instance"
    inst.mkdir()
    return inst


def _snapshot(root: Path):
    return sorted((str(p), p.stat().st_mtime_ns) for p in root.rglob("*"))


def prop(tool="write_file", actor="owner:matthew", **ctx):
    return ProposedAction(tool_name=tool, arguments={"path": "notes.txt"}, actor=actor, context=ctx)


def test_team_deny_beats_local_allow_and_preview_explains(iso):
    store = ReviewRuleStore.for_instance(iso)
    store.save({"scope": "local", "subject": "write_file", "effect": "allow"})
    team, _ = store.save({"scope": "team", "subject": "write_file", "effect": "deny", "note": "org policy"})
    out = PolicyKernel().preview(prop(), instance_root=iso)
    assert out["decision"] == "deny"
    assert out["winning_rule"]["rule_id"] == team.rule_id and out["winning_rule"]["scope"] == "team"
    assert [r["why"] for r in out["overridden_rules"]] == ["team rule wins"]
    assert out["policy_name"] == "review_rules:team"
    # the live path enforces the same conflict at the authority layer
    d = PolicyKernel().evaluate(prop(), instance_root=iso)
    assert d.decision == AuthorityDecisionType.DENY and "Team review rule" in d.reason


def test_stale_local_edit_is_refused_after_team_change_and_preview_recomputes(iso):
    store = ReviewRuleStore.for_instance(iso)
    base = store.revisions()["local"]
    store.save({"scope": "team", "subject": "write_file", "effect": "require_approval"})
    store.save({"scope": "local", "subject": "read_file", "effect": "deny"}, expected_revision=base)
    with pytest.raises(StaleRuleRevision) as exc:
        store.save({"scope": "local", "subject": "write_file", "effect": "allow"}, expected_revision=base)
    assert exc.value.current == base + 1
    pending = ReviewRule.build({"scope": "local", "subject": "write_file", "effect": "allow"})
    out = PolicyKernel().preview(prop(), instance_root=iso, extra_rules=[pending])
    assert out["decision"] == "require_approval" and out["pending_rules_previewed"] == 1
    assert out["overridden_rules"][0]["pending"] is True


def test_replayed_save_makes_one_revision(iso):
    store = ReviewRuleStore.for_instance(iso)
    a, created_a = store.save({"scope": "team", "subject": "shell", "effect": "deny"}, idempotency_key="k1")
    b, created_b = store.save({"scope": "team", "subject": "shell", "effect": "deny"}, idempotency_key="k1")
    c, created_c = store.save({"scope": "team", "subject": "shell", "effect": "deny"})
    assert (created_a, created_b, created_c) == (True, False, False)
    assert a.revision == b.revision == c.revision == 1
    assert len(store.history()) == 1


def test_app_grants_one_revision_per_app_and_principal_viewing_and_input_separate(iso):
    store = ReviewRuleStore.for_instance(iso)
    rule = {"scope": "local", "subject": "app:com.apple.Safari", "principal": "agent:jaeger",
            "capability": "input", "effect": "deny"}
    store.save(rule)
    store.save(rule)
    assert len(store.history()) == 1
    k = PolicyKernel()
    deny_input = k.preview(prop("computer_use", "agent:jaeger", app_id="com.apple.Safari", capability="input"),
                           instance_root=iso)
    view = k.preview(prop("computer_use", "agent:jaeger", app_id="com.apple.Safari", capability="screen_view"),
                     instance_root=iso)
    assert deny_input["winning_rule"]["capability"] == "input" and deny_input["decision"] == "deny"
    assert view["winning_rule"] is None


def test_allow_rule_never_broadens(iso):
    ReviewRuleStore.for_instance(iso).save({"scope": "team", "subject": "*", "effect": "allow"})
    out = PolicyKernel().preview(prop("run_command", "guest"), instance_root=iso)
    assert out["decision"] == "deny"  # untrusted actor gate still decides


def test_corrupt_rules_fail_closed(iso):
    (iso / K.REVIEW_RULES_FILENAME).write_text("{not json")
    d = PolicyKernel().evaluate(prop(), instance_root=iso)
    assert d.decision == AuthorityDecisionType.DENY and "fail-closed" in d.reason


def test_dry_run_has_no_side_effects(iso, tmp_path, monkeypatch):
    from jaeger_agent import shell_hooks
    from jaeger_ai.core.gateway.global_stop import GlobalStop
    from jaeger_ai.core.runtime.lifecycle_lease import LifecycleLease
    from jaeger_ai.core.entity import runtime as rt

    def boom(*a, **kw):
        raise AssertionError("side effect in dry run")

    monkeypatch.setattr(shell_hooks, "fire", boom, raising=False)
    monkeypatch.setattr(rt.EntityRuntime, "get_singleton", classmethod(boom), raising=False)
    monkeypatch.setattr(GlobalStop, "load", classmethod(boom))
    monkeypatch.setattr(LifecycleLease, "load", classmethod(boom))
    before = _snapshot(tmp_path)
    out = PolicyKernel().preview(prop(), instance_root=iso)
    assert out["hooks_evaluated"] is False and out["action_authorized"] is False
    assert any(s["check"] == "shell_hooks" and s["outcome"] == "not_evaluated" for s in out["steps"])
    assert _snapshot(tmp_path) == before
    assert not (iso / K.REVIEW_RULES_FILENAME).exists()
