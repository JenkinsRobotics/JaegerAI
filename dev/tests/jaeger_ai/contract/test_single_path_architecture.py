"""One Gateway, one task authority, one event stream, one identity, one memory writer.

These read the source. They fail when a second authority appears: a second task
owner, a second completion writer, a production turn that bypasses the Gateway, a
second event bus, a second identity writer, a worker that writes durable memory, or
a second execution engine reachable from normal user input.

The allowlists below are the architecture, written down. Adding to one is a
decision to be made in review, not a side effect of a change.
"""
from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SOURCE_ROOTS = [ROOT / "jaeger_ai", *sorted((ROOT / "packages").glob("*/"))]
_SKIP = ("/tests/", "/test_", "/node_modules/", "/vendor/", "/__pycache__/", "/skills/", "/dev/")


@lru_cache(maxsize=1)
def _sources() -> dict[str, tuple[str, ast.AST]]:
    found: dict[str, tuple[str, ast.AST]] = {}
    for base in SOURCE_ROOTS:
        for path in base.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if any(part in "/" + rel for part in _SKIP):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            try:
                found[rel] = (text, ast.parse(text))
            except SyntaxError:
                continue
    return found


def _modules_where(predicate) -> set[str]:
    return {rel for rel, (text, tree) in _sources().items() if predicate(rel, text, tree)}


def _attribute_names(tree: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name):
                out.append(n)
    return out


# ── 1. one task authority ───────────────────────────────────────────────────

def test_gateway_task_owner_is_the_only_task_owner():
    owners = {
        (rel, n.name)
        for rel, (_, tree) in _sources().items()
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and re.search(r"TaskOwner$", n.name)
    }
    assert owners == {("jaeger_ai/core/tasks/owner.py", "GatewayTaskOwner")}


def test_there_is_one_durable_task_store():
    stores = {
        (rel, n.name)
        for rel, (_, tree) in _sources().items()
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef)
        and any(isinstance(b, ast.FunctionDef) and b.name == "admit_task" for b in n.body)
    }
    assert stores == {("jaeger_ai/core/tasks/store.py", "SqliteDurableTaskStore")}


# ── 2. one completion authority ─────────────────────────────────────────────

def test_only_the_task_package_names_the_verified_state():
    named = _modules_where(lambda rel, text, tree: "COMPLETED_VERIFIED" in _attribute_names(tree) | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)})
    assert named <= {
        "jaeger_ai/core/tasks/models.py",
        "jaeger_ai/core/tasks/completion.py",
        "jaeger_ai/core/tasks/owner.py",
    }, named


def test_no_code_assigns_a_task_state_outside_the_task_package():
    def assigns_state(rel, text, tree):
        if rel.startswith("jaeger_ai/core/tasks/"):
            return False
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "state" for t in n.targets):
                v = n.value
                if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "TaskState":
                    return True
        return False
    assert _modules_where(assigns_state) == set()


def test_authoritative_transition_is_called_only_by_the_task_owner():
    callers = _modules_where(lambda rel, text, tree: bool(_calls(tree, "authoritative_transition")))
    assert callers == {"jaeger_ai/core/tasks/owner.py"}


def test_completion_never_accepts_a_bare_success_as_evidence():
    from jaeger_ai.core.tasks.completion import CompletionError, authoritative_transition
    from jaeger_ai.core.tasks.models import DurableTask, TaskState

    for evidence in (None, "", [], {}, "ok", "success", "done", "completed", {"status": "ok"}, {"success": True}):
        task = DurableTask("t", "a", "g")
        with pytest.raises(CompletionError):
            authoritative_transition(task, TaskState.COMPLETED_VERIFIED, evidence=evidence)
        assert task.state is TaskState.QUEUED


# ── 3. workers do not own state ─────────────────────────────────────────────

_WORKER_ROOTS = ("packages/jaeger-agent/jaeger_agent/delegates/", "jaeger_ai/features/ide_orchestration/")
_AUTHORITIES = (
    "jaeger_ai.core.tasks", "jaeger_ai.core.entity.memory", "jaeger_ai.core.entity.event_store",
    "jaeger_ai.core.entity.identity", "jaeger_agent.memory", "jaeger_ai.core.gateway.event_bus",
    "jaeger_ai.core.gateway.session_store",
)


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module)
            names |= {f"{n.module}.{a.name}" for a in n.names}
    return names


#: Delegate effectiveness observations are the router's own telemetry (latency, success
#: rate per runtime), kept in the shared SQLite file. They are not memory of the owner,
#: the world or Jaeger, and no category the ownership registry names is written here.
_WORKER_TELEMETRY = {"packages/jaeger-agent/jaeger_agent/delegates/health/store.py"}


def test_workers_import_none_of_the_authorities():
    offenders = {
        rel: sorted(i for i in _imports(tree) if i.startswith(_AUTHORITIES))
        for rel, (_, tree) in _sources().items()
        if rel.startswith(_WORKER_ROOTS) and rel not in _WORKER_TELEMETRY
    }
    assert {k: v for k, v in offenders.items() if v} == {}


# ── 4. one event stream ─────────────────────────────────────────────────────

def test_the_gateway_event_bus_is_the_only_event_bus():
    buses = {
        (rel, n.name)
        for rel, (_, tree) in _sources().items()
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and re.search(r"(EventBus|ActivityBus)$", n.name)
    }
    # The chassis bus in jaeger-os routes in-process node messages; it never carries
    # Jaeger state to clients. Presence and task events exist only on the Gateway bus.
    assert ("jaeger_ai/core/gateway/event_bus.py", "GatewayEventBus") in buses
    assert not [b for b in buses if "ActivityBus" in b[1]]
    assert {b for b in buses if b[0].startswith("jaeger_ai/")} == {
        ("jaeger_ai/core/gateway/event_bus.py", "GatewayEventBus")}


def test_presence_is_published_only_through_the_gateway_bus():
    literal = _modules_where(lambda rel, text, tree: '"jaeger.state"' in text or "'jaeger.state'" in text)
    assert literal == {"jaeger_ai/core/gateway/event_bus.py"}
    callers = _modules_where(lambda rel, text, tree: bool(_calls(tree, "publish_state")))
    assert callers <= {"jaeger_ai/core/gateway/server.py", "jaeger_ai/core/gateway/event_bus.py"}


# ── 5. one identity ─────────────────────────────────────────────────────────

def test_the_entity_identity_file_has_one_writer():
    writers = _modules_where(lambda rel, text, tree: bool(_calls(tree, "save_to_file")))
    assert writers == {"jaeger_ai/core/entity/identity.py"}


def test_only_the_identity_tool_renames_jaeger_at_runtime():
    # The agent package cannot import the product, so the identity tool reaches the
    # authority through an injected hook that identity.py alone registers.
    assert _modules_where(lambda rel, text, tree: bool(_calls(tree, "rename_entity"))) == set()
    registrants = _modules_where(lambda rel, text, tree: bool(_calls(tree, "set_name_authority")))
    assert registrants == {"jaeger_ai/core/entity/identity.py"}


#: identity.yaml is a configuration input the owner edits in setup and settings, and
#: the projection of the entity's name. These files may write it; a new one may not.
_IDENTITY_YAML_WRITERS = {
    "jaeger_ai/core/instance/setup_wizard.py", "jaeger_ai/core/instance/onboarding_setup.py",
    "jaeger_ai/core/instance/first_boot.py", "jaeger_ai/interfaces/bridge.py",
    "jaeger_ai/interfaces/pyside6/settings/window.py", "jaeger_ai/main.py",
    "jaeger_ai/core/runtime/_shakedown.py", "packages/jaeger-agent/jaeger_agent/tools/identity_tools.py",
}


def test_identity_yaml_is_written_only_by_setup_settings_and_the_identity_tool():
    def writes_identity_yaml(rel, text, tree):
        for call in _calls(tree, "dump_yaml"):
            if call.args and "identity_path" in ast.unparse(call.args[0]):
                return True
        return False
    assert _modules_where(writes_identity_yaml) <= _IDENTITY_YAML_WRITERS


@pytest.mark.parametrize("tool", ["set_name", "update_soul", "adjust_trait"])
@pytest.mark.parametrize("actor", ["mcp", "a2a", "agent:jaeger", "helper:x"])
def test_identity_tools_are_owner_only(tool, actor):
    from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction
    assert PolicyKernel().evaluate(ProposedAction(tool, {}, actor=actor)).decision is AuthorityDecisionType.DENY


# ── 6. one memory writer ────────────────────────────────────────────────────

@pytest.mark.parametrize("tool", ["remember", "forget", "memory", "remember_person"])
@pytest.mark.parametrize("actor", ["mcp", "a2a", "mcp:openclaw", "helper:x", "guest"])
def test_outside_callers_cannot_write_durable_memory(tool, actor):
    from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction
    decision = PolicyKernel().evaluate(ProposedAction(tool, {"key": "k", "value": "v"}, actor=actor))
    assert decision.decision is AuthorityDecisionType.DENY and decision.policy_name == "memory_authority"


def test_agent_facts_are_written_only_by_the_memory_tools_and_the_store_adapters():
    def writes_facts(rel, text, tree):
        for call in _calls(tree, "remember") + _calls(tree, "forget"):
            if isinstance(call.func, ast.Attribute) and re.search(r"\bmem\w*\b|_mem\b", ast.unparse(call.func.value)):
                return True
        return False
    assert _modules_where(writes_facts) <= {
        "packages/jaeger-agent/jaeger_agent/tools/memory.py",
        "packages/jaeger-agent/jaeger_agent/memory/sqlite_adapter.py",
        "packages/jaeger-agent/jaeger_agent/memory/sqlite_knowledge.py",
        # The periodic fact review of the isolated local runtime. It is reached only from
        # _run_turn, which fails closed unless JAEGER_LEGACY_PATHS is set.
        "jaeger_ai/main.py",
    }


def test_the_ownership_registry_names_one_owner_for_tasks_events_and_identity():
    from jaeger_ai.core.state.ownership import STATE_OWNERSHIP_REGISTRY, StateDomain
    assert STATE_OWNERSHIP_REGISTRY[StateDomain.TASKS].write_access == ("GatewayTaskOwner",)
    assert STATE_OWNERSHIP_REGISTRY[StateDomain.EVENT_STREAM].write_access == ("GatewayEventBus",)
    assert STATE_OWNERSHIP_REGISTRY[StateDomain.IDENTITY].authoritative_class == "EntityIdentity"


# ── 7. no second execution engine behind normal user input ──────────────────

def _function(rel: str, name: str) -> ast.FunctionDef:
    tree = _sources()[rel][1]
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


@pytest.mark.parametrize("name", ["run_for_voice", "_run_turn"])
def test_the_in_process_turn_is_guarded_by_the_legacy_switch(name):
    fn = _function("jaeger_ai/main.py", name)
    guards = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
              and getattr(c.func, "id", getattr(c.func, "attr", "")) == "require_legacy_path"]
    assert guards, f"{name} can run without JAEGER_LEGACY_PATHS"


def test_local_turn_executors_are_reachable_only_from_the_guarded_entry_points():
    runners = _modules_where(lambda rel, text, tree: bool(_calls(tree, "execute_turn")))
    assert runners <= {"jaeger_ai/main.py", "jaeger_ai/core/resilience/fault_injector.py"}, runners


def test_agent_loops_are_built_only_by_known_owners():
    builders = _modules_where(lambda rel, text, tree: bool(_calls(tree, "build_jaeger_agent")))
    assert builders <= {
        "jaeger_ai/main.py",                     # the isolated local runtime
        "jaeger_ai/core/entity/runtime.py",      # the Gateway's resident Entity (the canonical worker)
        "jaeger_ai/core/mind_runtime.py",        # runtime adapter for the isolated local runtime
        "jaeger_ai/core/runtime/subagents.py",   # a child of the Entity's turn
        "jaeger_ai/core/bench/runner.py",        # the benchmark harness
    }, builders


def test_the_cli_one_shot_is_admitted_by_the_gateway_before_any_local_runtime_starts():
    text, tree = _sources()["jaeger_ai/main.py"]
    entry = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and "return _forward_oneshot_to_gateway(oneshot" in (ast.get_source_segment(text, n) or "")
    )
    body = ast.get_source_segment(text, entry)
    assert body.index("return _forward_oneshot_to_gateway(oneshot") < body.index("lock = InstanceLock(layout)")


def test_bridge_local_execution_needs_the_legacy_switch(monkeypatch):
    from jaeger_ai.interfaces import bridge
    monkeypatch.setenv("JAEGER_BRIDGE_EXECUTION", "local")
    monkeypatch.delenv("JAEGER_LEGACY_PATHS", raising=False)
    assert bridge.gateway_execution_enabled() is True


def test_the_native_mcp_lead_lane_is_behind_the_legacy_switch():
    text = _sources()["jaeger_ai/core/gateway/server.py"][0]
    call = text.index("_run_native_coro(prompt), loop)")
    assert "legacy_paths_enabled()" in text[max(0, call - 400):call]


def test_the_gateway_routes_operational_turns_through_the_task_owner():
    text = _sources()["jaeger_ai/core/gateway/server.py"][0]
    assert "self.task_owner.open_turn(" in text and "self.task_owner.close_turn(" in text


# ── 8. avatars and embodiment are adapters ──────────────────────────────────

_AVATAR_ROOTS = ("jaeger_ai/interfaces/avatar", "jaeger_ai/interfaces/avatar_chat",
                 "jaeger_ai/interfaces/avatar_player")
_AVATAR_FORBIDDEN = (
    "jaeger_ai.core.tasks", "jaeger_ai.core.entity", "jaeger_ai.core.authority",
    "jaeger_ai.core.gateway.session_store", "jaeger_ai.core.gateway.server",
    "jaeger_ai.core.gateway.event_bus", "jaeger_agent.memory", "jaeger_ai.core.world",
)


def test_avatar_surfaces_own_no_memory_identity_goals_permissions_or_task_state():
    """An avatar renders Gateway state. It does not decide, remember or authorize."""
    offenders = {
        rel: sorted(i for i in _imports(tree) if i.startswith(_AVATAR_FORBIDDEN))
        for rel, (_, tree) in _sources().items() if rel.startswith(_AVATAR_ROOTS)
    }
    assert {k: v for k, v in offenders.items() if v} == {}


def test_embodiment_stays_closed_and_minecraft_is_not_an_agent():
    from jaeger_ai.core.embodiment.gate import EmbodimentDisabled, minecraft_action
    with pytest.raises(EmbodimentDisabled):
        minecraft_action("chat", text="hi")
    # The tool module opens no socket and runs no loop of its own.
    tree = _sources()["packages/jaeger-agent/jaeger_agent/tools/minecraft.py"][1]
    imported = {i.split(".")[0] for i in _imports(tree)}
    assert not imported & {"urllib", "socket", "http", "requests", "httpx", "subprocess", "threading", "asyncio"}
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    assert _modules_where(lambda rel, t, tree: "minecraft_action" in t) <= {
        "jaeger_ai/core/embodiment/gate.py"}


def test_every_worker_dispatch_opens_a_card_on_the_task_owner():
    """Both orchestration admissions (new task, follow-up) hand the owner a card to settle."""
    text = _sources()["jaeger_ai/core/gateway/server.py"][0]
    assert text.count("self.task_owner.open_dispatch(") == 2
    assert text.count("self._settle_dispatch(") == 2 and "def _settle_dispatch(" in text
    # The orchestration service never settles an authoritative state itself.
    service = _sources()["jaeger_ai/features/ide_orchestration/service.py"][1]
    assert "authoritative_transition" not in {n.id for n in ast.walk(service) if isinstance(n, ast.Name)}


# ── 9. disconnected code is deleted and must never reappear ─────────────────

_FORBIDDEN_DEAD_PACKAGES = {
    "jaeger_ai/mind": "a parallel cognition stack deleted in architecture cleanup",
    "jaeger_ai/interfaces/messaging": "legacy messaging adapters deleted in architecture cleanup",
}


@pytest.mark.parametrize("rel_path", sorted(_FORBIDDEN_DEAD_PACKAGES))
def test_disconnected_packages_are_deleted_and_do_not_reappear(rel_path):
    target = ROOT / rel_path
    assert not target.exists(), f"{rel_path} was deleted: {_FORBIDDEN_DEAD_PACKAGES[rel_path]}"
