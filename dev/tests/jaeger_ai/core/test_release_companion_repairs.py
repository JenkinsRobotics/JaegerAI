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
