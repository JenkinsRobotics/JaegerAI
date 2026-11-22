"""An approval nobody answered must stop looking answerable.

Live defect (2026-09-21 audit): the tool-confirm waiter gave up after 300 s
and refused the tool call, but the approval row stayed ``pending``. The phone
kept offering it, and approving it then did nothing at all.
"""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway import server as gateway_server
from jaeger_ai.core.gateway.server import (
    JaegerGatewayApp, _GatewayLocalReadAccessProvider, _GatewayLocalWriteAccessProvider,
    _GatewayToolConfirmationProvider,
)
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.fixture
def running_app(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "approvals.sqlite3"))
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    app._loop = loop
    yield app
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def _write_request():
    from jaeger_os.core.safety.permissions import PermissionTier

    return SimpleNamespace(
        tier=PermissionTier.WRITE_LOCAL, skill="files", operation="write_file",
        summary="write a file in the skills workspace",
        arguments={"path": "workspace/audit/a.txt", "content": "x" * 5000},
    )


@pytest.fixture(autouse=True)
def ask_mode():
    """These tests exercise the approval prompt, which is the operator's opt-in
    (autonomy "ask"/"scoped"); the default "auto" approves without asking."""
    from jaeger_ai.core.runtime import autonomy

    before = dict(autonomy._state)
    autonomy.set_autonomy("ask")
    yield
    autonomy._state.clear()
    autonomy._state.update(before)


def test_unanswered_approval_is_expired_when_the_tool_is_refused(running_app, monkeypatch):
    monkeypatch.setattr(gateway_server, "APPROVAL_WAIT_S", 0.3)
    provider = _GatewayToolConfirmationProvider(running_app, "s", "r")
    created = []
    original = running_app.store.create_approval

    def record(**kwargs):
        created.append(kwargs["approval_id"])
        return original(**kwargs)

    monkeypatch.setattr(running_app.store, "create_approval", record)

    assert provider.confirm(_write_request()) is False

    assert running_app.store.list_pending_approvals() == []
    row = running_app.store.get_approval(created[0])
    assert row["status"] == "resolved"
    assert row["decision"] == "expired"
    assert not running_app.pending_approvals


def test_answer_that_lands_first_is_honoured(running_app, monkeypatch):
    monkeypatch.setattr(gateway_server, "APPROVAL_WAIT_S", 0.3)
    provider = _GatewayToolConfirmationProvider(running_app, "s", "r")
    original = running_app.store.resolve_approval

    def operator_wins(approval_id, *, approved, decision=None):
        if decision == "expired":
            original(approval_id, approved=True, decision="once")
        return original(approval_id, approved=approved, decision=decision)

    monkeypatch.setattr(running_app.store, "resolve_approval", operator_wins)

    assert provider.confirm(_write_request()) is True


def test_prompt_names_the_target_not_just_the_operation(running_app, monkeypatch):
    """The phone showed "write a file in the skills workspace" for a write
    aimed at ~/JaegerAuditWorkspace, and ``reason: "1"`` for the tier."""
    monkeypatch.setattr(gateway_server, "APPROVAL_WAIT_S", 0.3)
    provider = _GatewayToolConfirmationProvider(running_app, "s", "r")
    created = []
    original = running_app.store.create_approval
    monkeypatch.setattr(
        running_app.store, "create_approval",
        lambda **kw: created.append(kw) or original(**kw),
    )

    provider.confirm(_write_request())

    [kw] = created
    assert kw["prompt"] == "Allow files.write_file? path=workspace/audit/a.txt"
    assert kw["metadata"]["reason"] == "WRITE_LOCAL"
    assert "content" not in kw["prompt"]


def test_restart_expires_tool_confirms_but_keeps_handoff_approvals(tmp_path):
    store = GatewaySessionStore(tmp_path / "restart.sqlite3")
    store.create_approval(kind="tool_confirm", prompt="p", options=["once", "deny"],
                          session_id="s", request_id="r", approval_id="approval_tool")
    store.create_approval(kind="handoff", prompt="p", options=["once", "deny"],
                          session_id="s", request_id="r", approval_id="approval_handoff")

    assert store.expire_orphaned_tool_confirms() == 1

    assert store.get_approval("approval_tool")["decision"] == "expired"
    assert [a["approval_id"] for a in store.list_pending_approvals()] == ["approval_handoff"]


def test_package_installs_name_the_package(running_app, monkeypatch):
    from jaeger_os.core.safety.permissions import PermissionTier

    monkeypatch.setattr(gateway_server, "APPROVAL_WAIT_S", 0.3)
    created = []
    original = running_app.store.create_approval
    monkeypatch.setattr(
        running_app.store, "create_approval",
        lambda **kw: created.append(kw) or original(**kw),
    )
    request = SimpleNamespace(
        tier=PermissionTier.PRIVILEGED, skill="packages", operation="install_package",
        summary="pip-install a third-party package", arguments={"package": "pytest"},
    )

    _GatewayToolConfirmationProvider(running_app, "s", "r").confirm(request)

    assert created[0]["prompt"] == "Allow packages.install_package? package=pytest"


def test_allow_for_this_session_skips_later_prompts_in_that_session_only(running_app, monkeypatch):
    running_app.store.ensure_session("s")
    running_app.store.ensure_session("other")
    provider = _GatewayToolConfirmationProvider(running_app, "s", "r")
    original = running_app.store.create_approval

    def answer(**kwargs):
        row = original(**kwargs)
        assert kwargs["options"] == ["once", "session", "deny"]

        def _resolve():
            running_app.store.resolve_approval(kwargs["approval_id"], approved=True, decision="session")
            running_app.pending_approvals.pop(kwargs["approval_id"]).set_result(True)
        running_app._loop.call_soon(_resolve)
        return row

    monkeypatch.setattr(running_app.store, "create_approval", answer)
    assert provider.confirm(_write_request()) is True
    metadata = running_app.store.get_session("s")["metadata"]
    assert metadata["session_grants"] == ["files"]
    assert metadata["session_grants_boot_id"] == running_app._session_grants_boot_id
    assert not (running_app.store.path.parent / "permissions.json").exists()
    monkeypatch.setattr(running_app.store, "create_approval",
                        lambda **k: (_ for _ in ()).throw(AssertionError("prompted again")))
    assert provider.confirm(_write_request()) is True
    forced = _write_request()
    forced.force_prompt = True
    monkeypatch.setattr(gateway_server, "APPROVAL_WAIT_S", 0.2)
    monkeypatch.setattr(running_app.store, "create_approval", original)
    assert provider.confirm(forced) is False  # policy-required prompts ignore session grants
    other = _GatewayToolConfirmationProvider(running_app, "other", "r2")
    assert "files" not in other._session_grants()


def test_session_grant_expires_on_gateway_restart_without_losing_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    path = tmp_path / "restart.sqlite3"
    first = JaegerGatewayApp(store=GatewaySessionStore(path))
    first.store.ensure_session("s")
    first.store.update_metadata("s", {"resume_marker": "kept"})
    _GatewayToolConfirmationProvider(first, "s", "r")._grant_for_session("files")

    restarted = JaegerGatewayApp(store=GatewaySessionStore(path))
    provider = _GatewayToolConfirmationProvider(restarted, "s", "r2")
    assert restarted.store.get_session("s")["metadata"]["resume_marker"] == "kept"
    assert provider._session_grants() == set()
    monkeypatch.setattr(provider, "_prompt", lambda request, **kwargs: False)
    assert provider.confirm(_write_request()) is False
    assert not (tmp_path / "permissions.json").exists()


@pytest.mark.parametrize("decision,second_allowed", [("once", False), ("always", True)])
def test_other_approval_scopes_keep_their_behavior(
    running_app, monkeypatch, tmp_path, decision, second_allowed,
):
    from jaeger_ai.core.runtime import autonomy
    autonomy.set_autonomy("scoped")  # Standing grants are a scoped-mode feature.
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_os.core.safety.permissions import PermissionTier

    layout = SimpleNamespace(root=tmp_path, config_path=tmp_path / "config.yaml")
    monkeypatch.setattr(EntityRuntime, "get_singleton",
                        classmethod(lambda cls, *a, **kw: SimpleNamespace(layout=layout)))
    running_app.store.ensure_session("s")
    provider = _GatewayToolConfirmationProvider(running_app, "s", "r")
    original = running_app.store.create_approval

    def answer(**kwargs):
        row = original(**kwargs)

        def resolve():
            running_app.store.resolve_approval(kwargs["approval_id"], approved=True, decision=decision)
            running_app.pending_approvals.pop(kwargs["approval_id"]).set_result(True)
        running_app._loop.call_soon(resolve)
        return row

    monkeypatch.setattr(running_app.store, "create_approval", answer)
    request = SimpleNamespace(tier=PermissionTier.EXTERNAL_EFFECT, skill="calendar",
                              operation="create_event", summary="create event", arguments={})
    assert provider.confirm(request) is True
    monkeypatch.setattr(provider, "_prompt", lambda request, **kwargs: False)
    assert provider.confirm(request) is second_allowed
    restarted = JaegerGatewayApp(store=GatewaySessionStore(running_app.store.path))
    after_restart = _GatewayToolConfirmationProvider(restarted, "s", "r2")
    monkeypatch.setattr(after_restart, "_prompt", lambda request, **kwargs: False)
    assert after_restart.confirm(request) is second_allowed
    assert (tmp_path / "permissions.json").exists() is second_allowed


def test_local_read_once_expands_only_the_current_turn(running_app, monkeypatch, tmp_path):
    running_app.store.ensure_session("s")
    target = tmp_path / "outside.txt"
    target.write_text("ok")
    provider = _GatewayLocalReadAccessProvider(running_app, "s", "r")
    monkeypatch.setattr(provider.confirmation, "_prompt_decision", lambda request: (True, "once"))

    assert provider(target) == str(target.resolve())
    assert provider(target) == str(target.resolve())
    assert "local_read_roots" not in running_app.store.get_session("s")["metadata"]

    later = _GatewayLocalReadAccessProvider(running_app, "s", "r2")
    monkeypatch.setattr(later.confirmation, "_prompt_decision", lambda request: (False, "deny"))
    assert later(target) is None


def test_local_read_session_grant_is_durable_and_path_scoped(running_app, monkeypatch, tmp_path):
    running_app.store.ensure_session("s")
    target = tmp_path / "allowed.txt"
    other = tmp_path / "other.txt"
    target.write_text("yes")
    other.write_text("no")
    provider = _GatewayLocalReadAccessProvider(running_app, "s", "r")
    monkeypatch.setattr(provider.confirmation, "_prompt_decision", lambda request: (True, "session"))
    assert provider(target) == str(target.resolve())

    later = _GatewayLocalReadAccessProvider(running_app, "s", "r2")
    monkeypatch.setattr(
        later.confirmation, "_prompt_decision",
        lambda request: (_ for _ in ()).throw(AssertionError("saved grant prompted again")),
    )
    assert later(target) == str(target.resolve())
    monkeypatch.setattr(later.confirmation, "_prompt_decision", lambda request: (False, "deny"))
    assert later(other) is None


def test_local_read_groups_checkout_files_under_one_repo_grant(running_app, monkeypatch, tmp_path):
    running_app.store.ensure_session("s")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    first = repo / "src" / "one.py"
    second = repo / "pkg" / "two.py"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("1")
    second.write_text("2")
    provider = _GatewayLocalReadAccessProvider(running_app, "s", "r")
    prompts = []

    def approve(request):
        prompts.append(request)
        return True, "once"

    monkeypatch.setattr(provider.confirmation, "_prompt_decision", approve)
    assert provider(first) == str(repo)
    assert provider(second) == str(repo)
    assert len(prompts) == 1
    assert prompts[0].arguments["path"] == str(repo)
    assert prompts[0].arguments["requested_path"] == str(first)


def test_local_read_never_offers_root_or_home(running_app, monkeypatch):
    running_app.store.ensure_session("s")
    provider = _GatewayLocalReadAccessProvider(running_app, "s", "r")
    monkeypatch.setattr(
        provider.confirmation, "_prompt_decision",
        lambda request: (_ for _ in ()).throw(AssertionError("broad root must not prompt")),
    )
    from pathlib import Path
    assert provider(Path.home()) is None
    assert provider(Path("/")) is None


def test_local_read_approval_resumes_the_same_resolver_call(running_app, monkeypatch, tmp_path):
    from jaeger_agent.core.workspace import _resolve_read, read_confinement

    running_app.store.ensure_session("s")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside" / "answer.txt"
    target.parent.mkdir()
    target.write_text("approved")
    original = running_app.store.create_approval

    def answer(**kwargs):
        row = original(**kwargs)
        assert kwargs["metadata"]["tool"] == "local_files.read_file"
        assert str(target) in kwargs["prompt"]

        def resolve():
            running_app.store.resolve_approval(
                kwargs["approval_id"], approved=True, decision="session",
            )
            running_app.pending_approvals.pop(kwargs["approval_id"]).set_result(True)
        running_app._loop.call_soon(resolve)
        return row

    monkeypatch.setattr(running_app.store, "create_approval", answer)
    provider = _GatewayLocalReadAccessProvider(running_app, "s", "r")
    with read_confinement([workspace], request_access=provider):
        assert _resolve_read(str(target)).read_text() == "approved"
    assert running_app.store.get_session("s")["metadata"]["local_read_roots"] == [str(target)]


def test_local_write_approval_resumes_and_persists_exact_scope(running_app, monkeypatch, tmp_path):
    running_app.store.ensure_session("s")
    target = tmp_path / "outside" / "answer.txt"
    provider = _GatewayLocalWriteAccessProvider(running_app, "s", "r")
    requests = []
    monkeypatch.setattr(
        provider.confirmation, "_prompt_decision",
        lambda request: requests.append(request) or (True, "session"),
    )
    assert provider(target) == str(target)
    assert requests[0].operation == "write_file"
    assert requests[0].arguments["access"] == "write"
    assert running_app.store.get_session("s")["metadata"]["local_write_roots"] == [str(target)]
