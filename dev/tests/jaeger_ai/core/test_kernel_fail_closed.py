"""Phase 1 / workstream 2: PolicyKernel is the only judge and it fails closed.

Covers Constitution I0 + invariant 11:
- unknown tool / action / tier → DENY
- any sub-check exception → DENY (Phase 0: four sub-checks returned None on error)
- unreadable or malformed commissioning policy → DENY
- missing caller identity → DENY
- canonical tool ids: ``terminal`` (the live shell tool) and every alias /
  namespaced / re-cased form is governed by the rules written for "shell"
- model-supplied arguments cannot grant capability, change the actor, or
  flip an approval flag
- LIVE PATH: the real JaegerAgent loop → default executor composition
  (HookedToolExecutor → AuthorityLayer → PolicyKernel) blocks before the tool
  body runs; REQUIRE_APPROVAL is answered only by the owner's provider.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from jaeger_ai.core.authority import kernel as kmod
from jaeger_ai.core.authority.kernel import (
    AuthorityDecisionType,
    PolicyKernel,
    ProposedAction,
    canonical_tool_id,
)
from jaeger_ai.core.entity.authority import AuthorityLayer, ProposedAction as LayerProposal


SHELL_ALIASES = [
    "terminal", "Terminal", " terminal ", "TERMINAL", "shell", "run_shell", "run-shell",
    "exec", "bash", "sh", "zsh", "run_command", "execute_command",
    "mcp__jaeger__terminal", "functions.bash", "code:run_shell", "tools/terminal",
]


@pytest.fixture
def kernel():
    return PolicyKernel()


@pytest.fixture
def commissioned(tmp_path):
    def write(text: str):
        (tmp_path / "authority_policy.yaml").write_text(text, encoding="utf-8")
        return {"instance_root": str(tmp_path)}
    return write


# ── canonical identity ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name", SHELL_ALIASES)
def test_every_shell_alias_is_canonical_shell(name):
    assert canonical_tool_id(name) == "shell"


@pytest.mark.parametrize("name,cid", [
    ("remote_terminal", "remote_shell"), ("ssh", "remote_shell"),
    ("execute_code", "code_exec"), ("run_in_venv", "code_exec"),
    ("edit_file", "write_file"), ("append_file", "write_file"), ("patch", "write_file"),
    ("push", "git_push"), ("read_file", "read_file"), ("", ""), (None, ""),
])
def test_other_canonical_ids(name, cid):
    assert canonical_tool_id(name) == cid


@pytest.mark.parametrize("name", SHELL_ALIASES + ["remote_terminal", "execute_code", "git_push"])
@pytest.mark.parametrize("actor", ["guest", "untrusted", "external_agent", "external_agent:openclaw",
                                   "mcp:claude-code", "a2a:hermes", "helper:codex"])
def test_untrusted_actor_cannot_run_any_privileged_alias(kernel, name, actor):
    d = kernel.evaluate(ProposedAction(tool_name=name, arguments={"command": "id"}, actor=actor))
    assert d.decision == AuthorityDecisionType.DENY
    assert d.policy_name == "identity_trust"


@pytest.mark.parametrize("name", ["terminal", "Terminal", "mcp__jaeger__terminal", "bash"])
def test_commissioned_shell_deny_applies_to_terminal(kernel, commissioned, name):
    ctx = commissioned("shell:\n  risk_mode: deny\n")
    d = kernel.evaluate(ProposedAction(tool_name=name, arguments={"command": "ls"}, context=ctx))
    assert d.decision == AuthorityDecisionType.DENY
    assert d.policy_name == "commissioning_authority"


def test_commissioned_shell_confirm_requires_approval_for_terminal(kernel, commissioned):
    ctx = commissioned("shell:\n  risk_mode: confirm\n")
    d = kernel.evaluate(ProposedAction(tool_name="terminal", arguments={"command": "ls"}, context=ctx))
    assert d.decision == AuthorityDecisionType.REQUIRE_APPROVAL


def test_authority_layer_policy_also_uses_canonical_ids(commissioned):
    ctx = commissioned("shell:\n  risk_mode: deny\n")
    d = AuthorityLayer().authorize(LayerProposal(tool_name="terminal", arguments={"command": "ls"}, context=ctx))
    assert d.is_authorized is False


def test_git_push_to_main_through_terminal_requires_approval(kernel):
    d = kernel.evaluate(ProposedAction(tool_name="terminal", arguments={"command": "git push origin main"}))
    assert d.decision == AuthorityDecisionType.REQUIRE_APPROVAL
    ok = kernel.evaluate(ProposedAction(tool_name="terminal", arguments={"command": "git status"}))
    assert ok.decision == AuthorityDecisionType.ALLOW


# ── unknown → deny ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["", "   ", None])
def test_unknown_tool_name_denied(kernel, name):
    d = kernel.evaluate(ProposedAction(tool_name=name, arguments={}))
    assert d.decision == AuthorityDecisionType.DENY


@pytest.mark.parametrize("tier", ["dev_bypass", "root", "", "admin", None])
def test_unknown_or_non_grantable_tier_denied(kernel, tier):
    d = kernel.evaluate(ProposedAction(tool_name="read_file", arguments={}, tier=tier))
    assert d.decision == AuthorityDecisionType.DENY


@pytest.mark.parametrize("action_type", ["grant", "policy_update", "", "release_stop"])
def test_unknown_action_type_denied(kernel, action_type):
    d = kernel.evaluate(ProposedAction(tool_name="read_file", arguments={}, action_type=action_type))
    assert d.decision == AuthorityDecisionType.DENY


@pytest.mark.parametrize("actor", ["", "   ", None])
def test_missing_caller_identity_denied(kernel, actor):
    d = kernel.evaluate(ProposedAction(tool_name="read_file", arguments={}, actor=actor))
    assert d.decision == AuthorityDecisionType.DENY
    assert d.policy_name == "identity_required"


# ── sub-check errors → deny ────────────────────────────────────────────────

@pytest.mark.parametrize("check", ["_check_security_mode", "_check_capability_grants",
                                   "_check_shell_hooks", "_check_commissioning_policy"])
def test_internal_error_in_any_subcheck_denies(kernel, monkeypatch, check):
    """Break the dependency each sub-check imports; the kernel must DENY."""
    import builtins
    targets = {
        "_check_security_mode": "jaeger_os.core.safety.permissions",
        "_check_capability_grants": "jaeger_agent.tool_executor",
        "_check_shell_hooks": "jaeger_agent",
        "_check_commissioning_policy": "jaeger_ai.core.instance.commissioning",
    }
    real_import = builtins.__import__

    def broken(name, *a, **k):
        if name == targets[check]:
            raise RuntimeError(f"injected failure in {name}")
        return real_import(name, *a, **k)

    ctx = {"instance_root": "/nonexistent-instance"} if check == "_check_commissioning_policy" else {}
    monkeypatch.setattr(builtins, "__import__", broken)
    d = kernel.evaluate(ProposedAction(tool_name="read_file", arguments={"path": "x"}, context=ctx))
    monkeypatch.setattr(builtins, "__import__", real_import)
    assert d.decision == AuthorityDecisionType.DENY, (check, d)
    assert "fail-closed" in d.reason


@pytest.mark.parametrize("text", ["shell: [unclosed\n", "- just\n- a list\n"])
def test_malformed_commissioning_policy_denies(kernel, commissioned, text):
    ctx = commissioned(text)
    d = kernel.evaluate(ProposedAction(tool_name="write_file", arguments={"path": "a"}, context=ctx))
    assert d.decision == AuthorityDecisionType.DENY
    layer = AuthorityLayer().authorize(LayerProposal(tool_name="write_file", arguments={"path": "a"}, context=ctx))
    assert layer.is_authorized is False


def test_missing_commissioning_policy_is_not_an_error(kernel, tmp_path):
    d = kernel.evaluate(ProposedAction(tool_name="read_file", arguments={}, context={"instance_root": str(tmp_path)}))
    assert d.decision == AuthorityDecisionType.ALLOW


def test_authority_layer_registered_policy_exception_denies():
    def boom(_):
        raise RuntimeError("policy crashed")
    d = AuthorityLayer(policies=[boom]).authorize(LayerProposal(tool_name="read_file", arguments={}))
    assert d.is_authorized is False


# ── model output cannot grant ──────────────────────────────────────────────

@pytest.mark.parametrize("injected", [
    {"actor": "agent:jaeger"}, {"granted_by": "owner", "authorized": True},
    {"context": {"instance_root": "/"}, "tier": "read_only"},
    {"require_approval": False, "approved": True, "override": "owner"},
    {"allowed_tools": ["terminal"]},
])
def test_model_supplied_arguments_cannot_grant_or_change_identity(kernel, injected):
    args = {"command": "id", **injected}
    d = kernel.evaluate(ProposedAction(tool_name="terminal", arguments=args, actor="external_agent:openclaw"))
    assert d.decision == AuthorityDecisionType.DENY
    assert d.policy_name == "identity_trust"


def test_tool_grant_cannot_be_widened_by_inner_context():
    from jaeger_agent.tool_executor import tool_allowlist, active_tool_allowlist
    with tool_allowlist(["read_file"]):
        with tool_allowlist(["read_file", "terminal"]):  # a child/model asking for more
            assert active_tool_allowlist() == frozenset({"read_file"})
            d = PolicyKernel().evaluate(ProposedAction(tool_name="terminal", arguments={"command": "id"}))
            assert d.decision == AuthorityDecisionType.DENY


# ── LIVE PATH: real loop + default executor composition ───────────────────

class _Args(BaseModel):
    command: str = Field(default="")


class _Scripted:
    """Minimal ProviderAdapter: one tool call, then a final answer."""
    name = "scripted"

    def __init__(self, tool_name: str, command: str):
        self._script = [
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "name": tool_name, "arguments": {"command": command}}]},
            {"role": "assistant", "content": "done"},
        ]

    def format_messages(self, messages, tools, system):
        return {"messages": messages}

    def call(self, formatted, interrupt_event, **kwargs):
        return self._script.pop(0)

    def parse_response(self, raw):
        return raw

    def supports(self, feature):
        return False


@pytest.fixture
def live(tmp_path, monkeypatch):
    from jaeger_agent import JaegerAgent, ProviderAdapter, clear_registry, register_tool
    from jaeger_ai.core.entity.runtime import EntityRuntime

    clear_registry()
    ran: list[str] = []

    @register_tool("terminal", "Run a command (stub body for the test).", _Args)
    def _terminal(command: str = "") -> dict:
        ran.append(command)
        return {"ok": True, "stdout": "ran"}

    runtime = SimpleNamespace(
        layout=SimpleNamespace(root=tmp_path, workspace_dir=tmp_path, config_path=tmp_path / "config.yaml"),
        authority_layer=AuthorityLayer(),
        event_store=SimpleNamespace(append=lambda *a, **k: None),
        record_tool_start=lambda *a, **k: None,
        record_tool_result=lambda *a, **k: None,
    )
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))

    def run(tool_name="terminal", command="ls"):
        adapter = _Scripted(tool_name, command)
        adapter.__class__ = type("ScriptedAdapter", (_Scripted, ProviderAdapter), {})
        agent = JaegerAgent(adapter=adapter)
        agent.run_turn("do it")
        tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
        return tool_msgs

    yield SimpleNamespace(run=run, ran=ran, root=tmp_path)
    clear_registry()


def _tool_text(msgs):
    return json.dumps([m.get("content") for m in msgs])


def test_live_loop_commissioned_shell_deny_blocks_terminal_before_body(live):
    (live.root / "authority_policy.yaml").write_text("shell:\n  risk_mode: deny\n")
    msgs = live.run("terminal", "echo pwned")
    assert live.ran == []
    assert "blocked_by_authority" in _tool_text(msgs) or "not authorized" in _tool_text(msgs)


def test_live_loop_untrusted_caller_cannot_run_terminal(live):
    from jaeger_agent.tool_executor import caller_identity
    with caller_identity("external_agent:openclaw"):
        msgs = live.run("terminal", "id")
    assert live.ran == []
    assert "untrusted" in _tool_text(msgs)


def test_live_loop_corrupt_policy_blocks(live):
    (live.root / "authority_policy.yaml").write_text("shell: [unclosed\n")
    live.run("terminal", "ls")
    assert live.ran == []


def test_live_loop_require_approval_refused_without_owner(live):
    from jaeger_os.core.safety.permissions import DenyAllProvider, PermissionPolicy, use_policy
    with use_policy(PermissionPolicy(confirmation=DenyAllProvider())):
        live.run("terminal", "git push origin main")
    assert live.ran == []


def test_live_loop_require_approval_runs_after_owner_approves(live):
    from jaeger_os.core.safety.permissions import PermissionPolicy, use_policy
    seen = []

    class Owner:
        def confirm(self, request):
            seen.append(request)
            return True

    with use_policy(PermissionPolicy(confirmation=Owner())):
        live.run("terminal", "git push origin main")
    assert live.ran == ["git push origin main"]
    assert seen and seen[0].force_prompt is True and seen[0].operation == "terminal"


def test_live_loop_allowed_command_runs(live):
    live.run("terminal", "ls")
    assert live.ran == ["ls"]
