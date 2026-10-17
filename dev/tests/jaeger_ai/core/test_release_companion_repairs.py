"""Regression tests for companion release repairs (Slices 1, 2, 3, 4, and 5)."""

from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

try:
    import msgspec  # noqa: F401
except ModuleNotFoundError:
    _shim = ModuleType("msgspec")

    class Struct:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

        def __init__(self, *args, **kwargs):
            ann = getattr(self.__class__, "__annotations__", {})
            for idx, key in enumerate(ann):
                if idx < len(args):
                    setattr(self, key, args[idx])
                elif key in kwargs:
                    setattr(self, key, kwargs[key])
                elif hasattr(self.__class__, key):
                    setattr(self, key, getattr(self.__class__, key))
            for k, v in kwargs.items():
                setattr(self, k, v)

    _shim.Struct = Struct
    _shim.field = lambda **kw: kw.get("default", None)
    _shim.ValidationError = ValueError
    _shim.convert = lambda raw, cls: cls(**raw) if isinstance(raw, dict) else raw
    _shim.json = SimpleNamespace(encode=lambda x: b"{}", decode=lambda b, type=None: {})
    _shim.msgpack = SimpleNamespace(encode=lambda x: b"", decode=lambda b, type=None: {})
    sys.modules["msgspec"] = _shim

try:
    import zmq  # noqa: F401
except ModuleNotFoundError:
    _zmq = ModuleType("zmq")
    _zmq.Context = object
    _zmq.Socket = object
    _zmq.PUB = 1
    _zmq.SUB = 2
    _zmq.REQ = 3
    _zmq.REP = 4
    _zmq.XPUB = 9
    _zmq.XSUB = 10
    _zmq.SUBSCRIBE = 6
    _zmq.NOBLOCK = 1
    _zmq.Again = Exception
    _zmq.ZMQError = Exception
    sys.modules["zmq"] = _zmq

from jaeger_ai.core.entity.events import EventType, JaegerEvent
from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.entity.learning import LearningPipeline, LearningTarget
from jaeger_ai.core.entity.self_state import SelfState
from jaeger_ai.core.entity.skills.promotion import SkillPromotionPipeline
from jaeger_ai.core.entity.sleep_time import SleepTimeJobType, SleepTimeProcessor
from jaeger_ai.core.entity.event_store import SqliteEventStore
from jaeger_ai.core.entity.verification import VerificationResult, VerificationStatus
from jaeger_agent.prompts.assemble import assemble_prompt, iter_fragments


def test_tool_events_carry_both_tool_and_tool_name() -> None:
    started = JaegerEvent.tool_started("write_file", {"path": "a.txt"}, call_id="c1")
    completed = JaegerEvent.tool_completed("write_file", {"ok": True, "path": "a.txt"}, call_id="c1", duration_s=0.1)
    failed = JaegerEvent.tool_failed("write_file", "disk full", call_id="c2", duration_s=0.1)

    assert started.payload["tool"] == "write_file"
    assert started.payload["tool_name"] == "write_file"
    assert completed.payload["tool"] == "write_file"
    assert completed.payload["tool_name"] == "write_file"
    assert failed.payload["tool"] == "write_file"
    assert failed.payload["tool_name"] == "write_file"


def test_learning_pipeline_records_real_tool_name_from_tool_completed_event(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "events.sqlite3")
    pipeline = LearningPipeline(tmp_path, store)
    ev = JaegerEvent.tool_completed("write_file", {"ok": True}, call_id="c-learn", duration_s=0.05)
    ver = VerificationResult(
        status=VerificationStatus.OBJECTIVE_VERIFIED,
        target_objective="Write file",
        evidence="File exists with expected bytes",
        verifier="file_write",
    )
    state = SelfState(identity=EntityIdentity.create_default("test-jaeger"))

    decision = pipeline.process_experience(ev, ver, state)

    assert LearningTarget.SEMANTIC in decision.targets
    assert decision.updates_applied["claim"]["subject"] == "tool:write_file"


def test_skill_promotion_rejects_placeholder_and_comment_only_code(tmp_path: Path) -> None:
    pipeline = SkillPromotionPipeline(tmp_path / "skills")

    comment_cand = pipeline.extract_candidate(
        name="learned_write_file",
        description="Comment-only placeholder",
        code="# verified write_file playbook\n",
    )
    ver_comment = pipeline.verify_candidate(comment_cand, lambda _code: True)
    assert ver_comment.passed is False
    assert pipeline.promote(comment_cand, ver_comment) is False

    stub_cand = pipeline.extract_candidate(
        name="learned_stub",
        description="Pass-only placeholder",
        code="def run():\n    pass\n",
    )
    ver_stub = pipeline.verify_candidate(stub_cand, lambda _code: True)
    assert ver_stub.passed is False
    assert pipeline.promote(stub_cand, ver_stub) is False

    real_cand = pipeline.extract_candidate(
        name="learned_real_helper",
        description="Real executable skill",
        code="def summarize_lines(text: str) -> int:\n    return len((text or '').splitlines())\n",
    )
    ver_real = pipeline.verify_candidate(real_cand, lambda code: "summarize_lines" in code)
    assert ver_real.passed is True
    assert pipeline.promote(real_cand, ver_real) is True
    smoke_text = (tmp_path / "skills" / "learned_real_helper" / "tests" / "smoke_test.py").read_text(encoding="utf-8")
    assert "importlib.util.spec_from_file_location" in smoke_text


def test_sleep_time_consolidation_and_skill_review_do_not_promote_placeholder_playbooks(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "events.sqlite3")
    for idx in range(3):
        store.append(
            JaegerEvent.tool_completed(
                "write_file",
                {"ok": True, "path": f"file_{idx}.txt"},
                call_id=f"call-{idx}",
                duration_s=0.1,
            )
        )
    store.append(
        JaegerEvent.tool_failed(
            "terminal",
            "command timed out",
            call_id="call-fail-1",
            duration_s=1.0,
        )
    )

    processor = SleepTimeProcessor(tmp_path, store)
    res = processor.run_sleep_cycle(
        reason="test_cycle",
        job_types=[
            SleepTimeJobType.CONSOLIDATION,
            SleepTimeJobType.REFLECTION,
            SleepTimeJobType.SKILL_CANDIDATE_REVIEW,
        ],
    )

    assert res.claims_recorded >= 3
    claims = processor.memory.semantic.list_recent(10)
    assert any(c.get("subject") == "tool:write_file" for c in claims)
    assert res.skills_promoted == 0
    assert "learned_write_file" not in processor.skill_pipeline.list_promoted_skills()


def test_lean_prompt_mode_omits_heavy_dynamic_fragments(tmp_path: Path) -> None:
    layout = SimpleNamespace(
        root=tmp_path,
        skills_dir=tmp_path / "skills",
        memory_dir=tmp_path / "memory",
        logs_dir=tmp_path / "logs",
        run_dir=tmp_path / "run",
        config_path=tmp_path / "config.yaml",
        identity_path=tmp_path / "identity.yaml",
        audit_log_path=tmp_path / "logs" / "audit.log",
    )
    (tmp_path / "identity.yaml").write_text("name: Jaeger\n", encoding="utf-8")
    names = [frag.name for frag, _ in iter_fragments(layout, mode="lean")]
    assert "three_laws" in names
    assert "identity_name" in names
    assert "framework" not in names
    assert "skill_index" not in names
    assert "board_digest" not in names
    assert "tool_catalog" not in names
    lean_text = assemble_prompt(layout, mode="lean")
    assert len(lean_text) < 4000


def test_code_bridge_enforces_allowlist_and_routes_through_executor(tmp_path: Path) -> None:
    import json
    from unittest.mock import patch
    from jaeger_ai.core.runtime.code_bridge import _BridgeServer
    from jaeger_agent.tool_executor import active_caller_identity, active_tool_allowlist

    sock = tmp_path / "b.sock"
    called = []

    class DummyExecutor:
        def execute(self, tool_def, args):
            called.append(
                (
                    tool_def.name,
                    dict(args),
                    active_caller_identity(),
                    active_tool_allowlist(),
                )
            )
            return {"ok": True, "echo": args}

    srv = _BridgeServer(
        sock,
        executor=DummyExecutor(),
        caller="owner:cli",
        allowed_tools=frozenset({"update_plan"}),
        bind_socket=False,
    )
    try:
        denied = srv._handle(json.dumps({"tool": "write_file", "args": {"path": "x"}}).encode("utf-8"))
        assert denied["ok"] is False
        assert denied["error_type"] == "permission_denied"
        assert not called

        fake_tool = SimpleNamespace(name="update_plan", interactive=False)
        with patch("jaeger_ai.core.runtime.code_bridge._dispatch", return_value=fake_tool):
            allowed = srv._handle(json.dumps({"tool": "update_plan", "args": {"step": "done"}}).encode("utf-8"))
        assert allowed["ok"] is True
        assert allowed["result"] == {"ok": True, "echo": {"step": "done"}}
        assert called == [("update_plan", {"step": "done"}, "owner:cli", frozenset({"update_plan"}))]
    finally:
        srv.stop()

def test_webui_new_session_and_mobile_companion_contracts() -> None:
    repo = Path(__file__).resolve().parents[4]
    boot_js = (repo / "jaeger_ai/features/webui/static/boot.js").read_text(encoding="utf-8")
    index_html = (repo / "jaeger_ai/features/webui/static/index.html").read_text(encoding="utf-8")
    style_css = (repo / "jaeger_ai/features/webui/static/style.css").read_text(encoding="utf-8")
    avatar_js = (repo / "jaeger_ai/features/webui/static/jaeger_avatar.js").read_text(encoding="utf-8")
    vrm_js = (repo / "jaeger_ai/features/webui/static/jaeger_avatar_vrm.js").read_text(encoding="utf-8")
    companion_js = (repo / "jaeger_ai/features/webui/static/jaeger_companion.js").read_text(encoding="utf-8")
    pwa_js = (repo / "jaeger_ai/features/webui/static/pwa-startup.js").read_text(encoding="utf-8")
    agents_js = (repo / "jaeger_ai/features/webui/static/jaeger_agents_panel.js").read_text(encoding="utf-8")
    panels_js = (repo / "jaeger_ai/features/webui/static/panels.js").read_text(encoding="utf-8")
    sessions_js = (repo / "jaeger_ai/features/webui/static/sessions.js").read_text(encoding="utf-8")
    ui_js = (repo / "jaeger_ai/features/webui/static/ui.js").read_text(encoding="utf-8")
    sw_js = (repo / "jaeger_ai/features/webui/static/sw.js").read_text(encoding="utf-8")
    routes_py = (repo / "jaeger_ai/features/webui/api/routes.py").read_text(encoding="utf-8")
    mirror_py = (repo / "jaeger_ai/features/webui/api/gateway_mirror.py").read_text(encoding="utf-8")
    specialists_py = (repo / "jaeger_ai/core/agent_registry/specialists.py").read_text(encoding="utf-8")

    # 1. Single Assistant Header (Avatar, Name, Summary, Connection Status, History toggle, New conversation, Voice Call)
    assert 'id="assistantHeaderAvatar"' in index_html
    assert 'id="assistantConnBadge"' in index_html
    assert 'id="assistantHeaderSummary"' in index_html
    assert '.assistant-header-summary' in style_css
    assert '#assistantHeaderSummary' in style_css
    assert 'id="btnAgentHistoryToggle"' in index_html
    assert 'id="btnTitlebarVoiceCall"' in index_html
    assert '<span class="new-chat-btn-label">New chat</span>' in index_html
    assert 'id="titlebarModeSwitch"' not in index_html

    # 2. Agent-First Sidebar + Per-Agent Workspace History Drawer (#agentHistoryDrawer)
    assert 'id="agentHistoryDrawer"' in index_html
    assert 'id="sidebarPrimaryNav"' in index_html
    assert 'id="navLinkProjects"' in index_html
    assert 'id="navLinkScheduled"' in index_html
    assert 'id="navLinkSettings"' in index_html
    assert "_ALWAYS_VISIBLE_TABS = new Set(['chat','kanban','tasks','profiles','settings']);" in panels_js

    # 3. Internal components (gateway, surfaces) & third-party adapters removed from user-facing agent list
    assert '"internal": True' in specialists_py
    assert "INTERNAL_IDS=new Set(['native:gateway','native:surfaces','gateway','surfaces'])" in agents_js
    assert "a.kind==='third_party'||id.startsWith('tp:')" in agents_js

    # 4. Simple Composer (Ask Jaeger placeholder; model/workspace/profile selectors tucked under #btnComposerOptions)
    assert 'placeholder="Ask Jaeger"' in index_html
    assert "msg.placeholder='Ask Jaeger" in boot_js
    assert 'id="btnComposerOptions"' in index_html
    assert "body:not(.composer-show-advanced) #profileChipWrap" in style_css
    assert "body:not(.composer-show-advanced) .composer-model-wrap" in style_css

    # 5. Non-overlapping notifications, cache eviction & session continuity
    assert "position:fixed;top:60px;right:20px;bottom:auto;" in companion_js
    assert "jaeger-companion-dismiss" in companion_js
    assert "jaeger-companion-reply-btn" in companion_js
    assert "Session not available in web UI." not in sessions_js
    assert "Jaeger is currently unreachable" not in pwa_js
    assert "jaeger-ui-build-v16" in pwa_js
    assert ".jaegerpd16" in sw_js
    assert "sid.startsWith('agent-')||meta.home===true||meta.agent_id" in boot_js
    assert "gateway_mirror.ensure_gateway_session(s)" in routes_py
    assert "def ensure_gateway_session(" in mirror_py
    assert "def is_mirrored_gateway_session(" in mirror_py
    assert "var(--keyboard-bottom-inset, 0px)" in avatar_js
    assert "3D avatar disabled on compact mobile viewport" in vrm_js
    assert "lastEl.classList.contains('msg-date-sep')" in ui_js


def test_webui_behavioral_new_chat_switching_reconnect_and_mobile_keyboard() -> None:
    """Prove agent filtering, New chat, session switching, and mobile keyboard draft preservation at runtime."""
    import os
    import shutil
    import subprocess

    repo = Path(__file__).resolve().parents[4]
    boot_src = (repo / "jaeger_ai/features/webui/static/boot.js").read_text(encoding="utf-8")

    start = boot_src.index("function _currentSessionIsReusableEmptyChat(){")
    depth = 0
    end = start
    for idx in range(start, len(boot_src)):
        ch = boot_src[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    fn_code = boot_src[start:end]

    node_bin = shutil.which("node") or "/opt/homebrew/bin/node"
    node_script = (
        "const fs = require('fs');\n"
        "const vm = require('vm');\n"
        "const assert = require('assert');\n"
        f"const fnCode = {fn_code!r};\n"
        "const agentsSrc = fs.readFileSync('jaeger_ai/features/webui/static/jaeger_agents_panel.js', 'utf8');\n"
        "const ctx = {\n"
        "  S: { session: { session_id: 'agent-jaeger', title: 'Jaeger', metadata: { home: true, agent_id: 'native:jaeger' } }, messages: [], busy: false, activeStreamId: null },\n"
        "  _attachFiles: [],\n"
        "  $: (id) => ({ value: '' }),\n"
        "  window: {},\n"
        "  document: { readyState: 'loading', addEventListener: () => {}, getElementById: () => null, querySelectorAll: () => [] },\n"
        "  fetch: async () => ({ ok: true, json: async () => ({ agents: [] }) }),\n"
        "  console: console,\n"
        "};\n"
        "ctx.window = ctx;\n"
        "vm.createContext(ctx);\n"
        "vm.runInContext(fnCode, ctx);\n"
        "vm.runInContext(agentsSrc, ctx);\n"
        "// Proof 1: sortAgents removes Gateway, Surfaces, and third-party adapters, keeping Jaeger + Everyday\n"
        "const filtered = ctx.jaegerAgents.sortAgents([\n"
        "  { id: 'native:jaeger', name: 'jaeger', display_name: 'Jaeger', role: 'lead', kind: 'native' },\n"
        "  { id: 'native:everyday', name: 'everyday', display_name: 'Everyday', role: 'specialist', kind: 'native' },\n"
        "  { id: 'native:gateway', name: 'gateway', display_name: 'Gateway', role: 'specialist', kind: 'native', metadata: { internal: true } },\n"
        "  { id: 'native:surfaces', name: 'surfaces', display_name: 'Surfaces', role: 'specialist', kind: 'native', metadata: { internal: true } },\n"
        "  { id: 'tp:hermes', name: 'hermes', display_name: 'Hermes Agent', role: 'specialist', kind: 'third_party' },\n"
        "  { id: 'tp:openclaw', name: 'openclaw', display_name: 'OpenClaw', role: 'specialist', kind: 'third_party' },\n"
        "  { id: 'tp:roundtable', name: 'roundtable', display_name: 'Roundtable', role: 'specialist', kind: 'third_party' },\n"
        "]);\n"
        "assert.deepStrictEqual(filtered.map(a => a.id), ['native:jaeger', 'native:everyday']);\n"
        "// Proof 2: New chat when on agent-jaeger home session is NEVER trapped as reusable empty chat\n"
        "assert.strictEqual(ctx._currentSessionIsReusableEmptyChat(), false, 'agent-jaeger home session must not trap New chat');\n"
        "// Proof 3: Switching to a custom-titled session is NEVER treated as an empty throwaway chat\n"
        "ctx.S.session = { session_id: '20261014_120000_abcd1234', title: 'Egypt Footage Audit', metadata: {} };\n"
        "assert.strictEqual(ctx._currentSessionIsReusableEmptyChat(), false, 'custom-titled session must not trap New chat');\n"
        "// Proof 4: Blank Untitled session with no draft IS reusable\n"
        "ctx.S.session = { session_id: '20261014_120100_efgh5678', title: 'Untitled', metadata: {} };\n"
        "assert.strictEqual(ctx._currentSessionIsReusableEmptyChat(), true, 'blank Untitled session is reusable');\n"
        "// Proof 5: Active draft text preserved across mobile keyboard/resize events\n"
        "ctx.$ = (id) => ({ value: 'Check recording 022' });\n"
        "assert.strictEqual(ctx._currentSessionIsReusableEmptyChat(), false, 'active draft text preserved across keyboard/session actions');\n"
        "// Proof 6: syncAssistantHeader populates #assistantHeaderSummary and title tooltip\n"
        "const headerElements = {\n"
        "  assistantHeaderAvatar: { innerHTML: '' },\n"
        "  appTitlebarTitle: { textContent: '', title: '' },\n"
        "  assistantHeaderSummary: { textContent: '' },\n"
        "  msg: { placeholder: '' },\n"
        "};\n"
        "ctx.document.getElementById = (id) => headerElements[id] || null;\n"
        "ctx.jaegerAgents.syncAssistantHeader({ id: 'native:jaeger', name: 'jaeger', display_name: 'Jaeger', role: 'lead', summary: 'Personal companion' });\n"
        "assert.strictEqual(headerElements.assistantHeaderSummary.textContent, 'Personal companion', 'assistantHeaderSummary must be populated with agent summary');\n"
        "assert.strictEqual(headerElements.appTitlebarTitle.title, 'Personal companion', 'appTitlebarTitle title tooltip must be populated with agent summary');\n"
        "console.log('ALL_BEHAVIORAL_PROOFS_OK');\n"
    )
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    res = subprocess.run(
        [node_bin, "-e", node_script],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "ALL_BEHAVIORAL_PROOFS_OK" in res.stdout
