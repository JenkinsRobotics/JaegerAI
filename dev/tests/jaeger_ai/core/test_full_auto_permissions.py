"""Phase 2 P0 regression suite — Full Auto, permissions, settings & session management.

Covers every required Gate A / Part 1 §2 regression check:
1. Full Auto changes an authorized Jaeger setting and verifies persistence.
2. Full Auto archives/deletes explicitly selected disposable sessions and verifies outcome.
3. Zero redundant approvals for authorized operations in Full Auto (including routine shell
   under commissioning confirm + already-granted framework_delegate).
4. Authority modes and persistent/expiring grants survive restart and revoke cleanly.
5. Delegated / external / background actors cannot exceed granted authority.
6. Unsupported actions return concrete technical error messages.
7. Catastrophic / destructive actions and explicit denies remain blocked even in Full Auto.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from jaeger_ai.core.authority.kernel import (
    AuthorityDecisionType,
    PolicyKernel,
    ProposedAction,
)
from jaeger_ai.core.frameworks.grants import FrameworkGrants
from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, dump_yaml
from jaeger_ai.core.runtime.autonomy import (
    autonomy_info,
    configured_autonomy,
    normalize_autonomy,
    set_autonomy,
)
from jaeger_ai.core.session_tools import session_manage
from jaeger_ai.core.settings.tools import settings_get, settings_set
from jaeger_os.core.safety.permissions import PermissionGrants


def _make_instance(tmp_path: Path, *, autonomy: str = "auto", shell_mode: str = "confirm") -> InstanceLayout:
    root = tmp_path / "inst"
    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    cfg = Config(instance_name="jaeger", model={"model_path": "unconfigured"})
    cfg.automation.autonomy = autonomy
    dump_yaml(layout.config_path, cfg)
    policy_path = root / "authority_policy.yaml"
    policy_path.write_text(
        yaml.safe_dump({
            "shell": {"risk_mode": shell_mode},
            "filesystem": {"write": True},
            "git": {"local_commit": True, "push": False},
        }),
        encoding="utf-8",
    )
    return layout


# ── 1. Full Auto changes an authorized Jaeger setting & persists ───────

def test_full_auto_changes_setting_and_blocks_protected_settings(tmp_path: Path):
    layout = _make_instance(tmp_path, autonomy="auto")

    # PolicyKernel allows owner settings_set
    decision = PolicyKernel().evaluate(
        ProposedAction(
            tool_name="settings_set",
            arguments={"path": "model.ctx", "value": 32768},
            actor="owner:webui",
            context={"instance_root": str(layout.root)},
        ),
        instance_root=layout.root,
        dry_run=True,
    )
    assert decision.decision == AuthorityDecisionType.ALLOW

    # Authorized setting persists and verifies on disk
    res = settings_set(layout, "model.ctx", 32768)
    assert res["ok"] is True and res["verified"] is True and res["persisted_value"] == 32768
    read_back = settings_get(layout, "model.ctx")
    assert read_back["ok"] is True and read_back["setting"]["current"] == 32768

    # Protected autonomy / security settings cannot be silently self-escalated
    blocked = settings_set(layout, "automation.autonomy", "auto")
    assert blocked["ok"] is False and blocked["error_type"] == "protected_setting"

    # Unknown setting returns a concrete error (never a generic refusal)
    unknown = settings_set(layout, "nonexistent.knob", 123)
    assert unknown["ok"] is False and "Unknown" in unknown["error"]


# ── 2. Full Auto archives & deletes explicitly specified test sessions ─

def test_session_manage_archives_deletes_verifies_and_rejects_wildcards(monkeypatch):
    store = {
        "disp-1": {"session_id": "disp-1", "title": "Temp 1", "archived": False, "messages": []},
        "disp-2": {"session_id": "disp-2", "title": "Temp 2", "archived": False, "messages": []},
        "keep-active": {"session_id": "keep-active", "title": "Active", "archived": False, "messages": []},
    }

    class FakeGateway:
        def get_session(self, sid):
            from jaeger_ai.core.gateway.client import GatewayUnavailable
            if sid not in store:
                raise GatewayUnavailable("HTTP 404")
            return dict(store[sid])

        def _call(self, method, path, body=None):
            from jaeger_ai.core.gateway.client import GatewayUnavailable
            sid = path.rsplit("/", 1)[-1]
            if sid not in store:
                raise GatewayUnavailable("HTTP 404")
            if method == "PATCH":
                store[sid]["archived"] = bool(body["archived"])
                return dict(store[sid])
            if method == "DELETE":
                del store[sid]
                return {"deleted": True}
            raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr("jaeger_ai.core.session_tools._gateway", lambda: FakeGateway())

    # Archive explicit session and verify
    arch = session_manage("archive", ["disp-1"])
    assert arch["ok"] is True and arch["verified"] is True and arch["succeeded"] == ["disp-1"]
    assert store["disp-1"]["archived"] is True

    # Delete two disposable test sessions and verify they are gone
    deleted = session_manage("delete", ["disp-1", "disp-2"], active_session_id="keep-active")
    assert deleted["ok"] is True and deleted["verified"] is True
    assert deleted["succeeded"] == ["disp-1", "disp-2"]
    assert "disp-1" not in store and "disp-2" not in store and "keep-active" in store

    # Refuses active session deletion and wildcards with concrete errors
    refuse_active = session_manage("delete", ["keep-active"], active_session_id="keep-active")
    assert refuse_active["ok"] is False and "active session" in refuse_active["error"]

    refuse_wild = session_manage("delete", ["*"])
    assert refuse_wild["ok"] is False and "wildcard" in refuse_wild["error"].lower()


def test_session_manage_delete_old_preserves_active_and_verifies(monkeypatch):
    from jaeger_ai.core.gateway.client import GatewayUnavailable

    store = {
        "active-now": {"session_id": "active-now", "title": "Current chat", "archived": False, "messages": []},
        "old-1": {"session_id": "old-1", "title": "Old chat 1", "archived": False, "messages": []},
        "old-2": {"session_id": "old-2", "title": "Old chat 2", "archived": False, "messages": []},
        "pinned-keep": {"session_id": "pinned-keep", "title": "Keep me", "archived": False, "messages": []},
    }

    class FakeGateway:
        def list_sessions(self):
            return list(store.values())

        def get_session(self, sid):
            if sid not in store:
                raise GatewayUnavailable("HTTP 404")
            return dict(store[sid])

        def _call(self, method, path, body=None):
            if method == "GET" and path == "/v1/sessions/active":
                return {"active_session_id": "active-now"}
            sid = path.rsplit("/", 1)[-1]
            if method == "DELETE":
                if sid not in store:
                    raise GatewayUnavailable("HTTP 404")
                del store[sid]
                return {"deleted": True}
            raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr("jaeger_ai.core.session_tools._gateway", lambda: FakeGateway())
    res = session_manage("delete_old", keep_session_ids=["pinned-keep"])
    assert res["ok"] is True and res["verified"] is True
    assert res["deleted_count"] == 2
    assert set(res["succeeded"]) == {"old-1", "old-2"}
    assert set(res["kept"]) == {"active-now", "pinned-keep"}
    assert set(store.keys()) == {"active-now", "pinned-keep"}


# ── 3. Zero redundant approvals in Full Auto vs Manual/Smart Auto ──────

def test_full_auto_removes_redundant_shell_and_granted_delegate_prompts(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    layout_auto = _make_instance(tmp_path / "auto", autonomy="auto", shell_mode="confirm")
    layout_scoped = _make_instance(tmp_path / "scoped", autonomy="scoped", shell_mode="confirm")

    # Routine non-destructive shell command: ALLOW in Full Auto, REQUIRE_APPROVAL in Smart Auto
    d_auto = PolicyKernel().evaluate(
        ProposedAction(tool_name="exec_command", arguments={"command": "pytest -q"}, actor="owner:cli"),
        instance_root=layout_auto.root,
        dry_run=True,
    )
    assert d_auto.decision == AuthorityDecisionType.ALLOW

    d_scoped = PolicyKernel().evaluate(
        ProposedAction(tool_name="exec_command", arguments={"command": "pytest -q"}, actor="owner:cli"),
        instance_root=layout_scoped.root,
        dry_run=True,
    )
    assert d_scoped.decision == AuthorityDecisionType.REQUIRE_APPROVAL

    # Already-granted framework_delegate: ALLOW in Full Auto, REQUIRE_APPROVAL in Smart Auto
    FrameworkGrants().set("codex", "delegate", True, by="owner:webui")
    d_del_auto = PolicyKernel().evaluate(
        ProposedAction(tool_name="framework_delegate", arguments={"framework": "codex", "goal": "run tests"}, actor="owner:webui"),
        instance_root=layout_auto.root,
        dry_run=True,
    )
    assert d_del_auto.decision == AuthorityDecisionType.ALLOW

    d_del_scoped = PolicyKernel().evaluate(
        ProposedAction(tool_name="framework_delegate", arguments={"framework": "codex", "goal": "run tests"}, actor="owner:webui"),
        instance_root=layout_scoped.root,
        dry_run=True,
    )
    assert d_del_scoped.decision == AuthorityDecisionType.REQUIRE_APPROVAL

    # Ungranted framework stays strictly DENIED even in Full Auto
    d_ungranted = PolicyKernel().evaluate(
        ProposedAction(tool_name="framework_delegate", arguments={"framework": "untrusted_fw"}, actor="owner:webui"),
        instance_root=layout_auto.root,
        dry_run=True,
    )
    assert d_ungranted.decision == AuthorityDecisionType.DENY


# ── 4. Authority modes, persistent grants, expiration & revocation ─────

def test_autonomy_aliases_and_persistent_grant_expiration_survive_restart(tmp_path: Path):
    assert normalize_autonomy("Manual") == "ask"
    assert normalize_autonomy("Smart Auto") == "scoped"
    assert normalize_autonomy("Full Auto") == "auto"
    assert set_autonomy("Full Auto")["label"] == "Full Auto"
    assert autonomy_info()["label"] == "Full Auto"

    layout = _make_instance(tmp_path, autonomy="auto")
    assert configured_autonomy(layout.config_path) == "auto"

    grants = PermissionGrants.load(layout.root)
    grants.grant_persistent("host")
    grants.grant_persistent("temp_skill", ttl_s=0.01)
    time.sleep(0.03)

    # Reload simulates controlled restart: permanent grant stays, expired grant dropped
    reloaded = PermissionGrants.load(layout.root)
    assert reloaded.is_granted("host") is True
    assert reloaded.is_granted("temp_skill") is False
    assert [g["skill"] for g in reloaded.inspect()] == ["host"]

    # Owner revocation persists across restart
    reloaded.revoke("host")
    assert PermissionGrants.load(layout.root).is_granted("host") is False


# ── 5. Delegated / external actors cannot exceed authority ─────────────

@pytest.mark.parametrize("tool", ["settings_set", "session_manage"])
@pytest.mark.parametrize("actor", ["mcp", "a2a", "mcp:codex", "helper:worker", "agent:jaeger", "guest"])
def test_delegated_and_external_actors_cannot_modify_settings_or_delete_sessions(tmp_path: Path, tool: str, actor: str):
    layout = _make_instance(tmp_path, autonomy="auto")
    decision = PolicyKernel().evaluate(
        ProposedAction(tool_name=tool, arguments={}, actor=actor),
        instance_root=layout.root,
        dry_run=True,
    )
    assert decision.decision == AuthorityDecisionType.DENY
    assert decision.policy_name == "owner_management_authority"


def test_gateway_caller_scopes_keep_session_delete_off_external_callers():
    assert caller_auth.required_scope("DELETE", "/v1/sessions/{id}") == "session_delete"
    assert "session_delete" in caller_auth.CALLERS["webui"].scopes
    assert "session_delete" in caller_auth.CALLERS["jaegerd"].scopes
    assert "admin" not in caller_auth.CALLERS["jaegerd"].scopes
    for external in ("mcp", "a2a", "ares", "codex", "claude", "grokbot", "hermes"):
        assert "session_delete" not in caller_auth.CALLERS[external].scopes


# ── 6 & 7. Dangerous actions remain blocked even in Full Auto ──────────

@pytest.mark.parametrize("tool,args", [
    ("exec_command", {"command": "rm -rf /Users/matthewjenkins/Documents"}),
    ("exec_command", {"command": "git reset --hard HEAD~3"}),
    ("exec_command", {"command": "git push --force origin master"}),
    ("framework_apply_diff", {"workspace": "/tmp/work"}),
])
def test_catastrophic_actions_stay_gated_even_in_full_auto(tmp_path: Path, tool: str, args: dict):
    layout = _make_instance(tmp_path, autonomy="auto", shell_mode="confirm")
    decision = PolicyKernel().evaluate(
        ProposedAction(tool_name=tool, arguments=args, actor="owner:webui"),
        instance_root=layout.root,
        dry_run=True,
    )
    assert decision.decision == AuthorityDecisionType.REQUIRE_APPROVAL


def test_explicit_shell_deny_is_never_overridden_by_full_auto(tmp_path: Path):
    layout = _make_instance(tmp_path, autonomy="auto", shell_mode="deny")
    decision = PolicyKernel().evaluate(
        ProposedAction(tool_name="exec_command", arguments={"command": "pytest -q"}, actor="owner:webui"),
        instance_root=layout.root,
        dry_run=True,
    )
    assert decision.decision == AuthorityDecisionType.DENY
    assert decision.policy_name == "commissioning_authority"


# ── 8. Desktop computer use: owner Full Auto ALLOW, untrusted DENY ──────

@pytest.mark.parametrize("tool", ["computer_do", "computer_use", "computer_click", "computer_type_text"])
def test_desktop_computer_use_allows_owner_in_full_auto_and_denies_external(tmp_path: Path, tool: str):
    layout = _make_instance(tmp_path, autonomy="auto")
    owner_decision = PolicyKernel().evaluate(
        ProposedAction(tool_name=tool, arguments={"action": "list_apps"}, actor="owner:webui", tier="external_effect"),
        instance_root=layout.root,
        dry_run=True,
    )
    assert owner_decision.decision == AuthorityDecisionType.ALLOW

    for actor in ("mcp", "mcp:codex", "a2a", "helper:worker", "guest", "external_agent:bot"):
        ext_decision = PolicyKernel().evaluate(
            ProposedAction(tool_name=tool, arguments={"action": "click"}, actor=actor, tier="external_effect"),
            instance_root=layout.root,
            dry_run=True,
        )
        assert ext_decision.decision == AuthorityDecisionType.DENY
        assert ext_decision.policy_name == "identity_trust"
