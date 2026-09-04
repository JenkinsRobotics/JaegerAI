"""Headless contracts for JaegerAI's multimodal face and worker."""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtWidgets import QApplication, QGroupBox  # noqa: E402

from jaeger_ai.interfaces.pyside6.multimodal.preflight import (  # noqa: E402
    Check,
    print_preflight,
)
from jaeger_ai.interfaces.pyside6.multimodal.selftest import selftest  # noqa: E402
from jaeger_ai.interfaces.pyside6.multimodal.window import MultimodalWindow  # noqa: E402
from jaeger_ai.interfaces.pyside6.multimodal.worker import (  # noqa: E402
    BorrowedRuntime,
    MultimodalWorker,
)
from jaeger_os.app.manifest import load_manifest  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _StubEngine:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.callback = kwargs["on_event"]
        self.speaking = SimpleNamespace(is_set=lambda: False)
        self.config = SimpleNamespace(fallback_llm_model_path="stub.gguf")
        self.node_llm = SimpleNamespace(runtime=SimpleNamespace(health=lambda: {"model": "stub"}))
        self.drain_input = lambda: None

    def set_barge_mode(self, _mode: str) -> None:
        return None

    def set_paused(self, _paused: bool) -> None:
        return None

    def force_listen(self) -> None:
        return None

    def close(self) -> None:
        return None


def test_worker_selftest_routes_every_event_kind() -> None:
    checks = selftest()
    assert len(checks) == 11
    assert [description for passed, description in checks if not passed] == []


def test_worker_has_three_input_queues_and_never_closes_borrowed_runtime() -> None:
    closed = []
    detached = []
    runtime = SimpleNamespace(
        close=lambda: closed.append(True),
        configure_vision=detached.append,
    )
    borrowed = BorrowedRuntime(runtime)
    borrowed.close()
    worker = MultimodalWorker(
        runtime=runtime,
        engine_factory=_StubEngine,
        agentic_tools=False,
    )
    worker.submit_text("hello")
    worker.submit_image("data:image/png;base64,AA==")
    worker.audio_q.put([0.0])
    assert worker.text_q.get_nowait() == "hello"
    assert worker.image_q.get_nowait().startswith("data:image/png")
    assert worker.audio_q.get_nowait() == [0.0]
    assert worker.engine.kwargs["runtime"].agentic_tools is False
    assert worker.engine.kwargs["output_mode"] == "speech"
    assert closed == []
    assert detached == [None]


def test_worker_completes_speech_only_output_without_a_blank_chat_commit(qapp) -> None:
    worker = MultimodalWorker(engine_factory=_StubEngine)
    commits = []
    outputs = []
    worker.commit.connect(lambda *args: commits.append(args))
    worker.output.connect(lambda *args: outputs.append(args))

    worker._on_event(
        SimpleNamespace(
            kind="assistant",
            text="",
            data={
                "display": False,
                "channels": ("speech",),
                "source": "model-output-directive",
            },
        )
    )

    assert commits == []
    assert outputs == [
        (
            "SPEECH",
            {
                "display": False,
                "channels": ("speech",),
                "source": "model-output-directive",
            },
        )
    ]
    assert worker._turns == 1


def test_borrowed_runtime_routes_chatbot_without_touching_agentic_turn() -> None:
    calls = []
    runtime = SimpleNamespace(
        run_turn=lambda *_args, **_kwargs: calls.append("agentic"),
        run_chatbot_turn=lambda text, **kwargs: calls.append(
            ("chatbot", text, kwargs["session_key"])
        ),
        warmup_chatbot=lambda **kwargs: calls.append(("warm", kwargs)) or True,
        clear_chatbot_session=lambda key: calls.append(("clear", key)),
    )
    borrowed = BorrowedRuntime(runtime, agentic_tools=False)

    borrowed.warmup(session_key="voice", system_prompt="brief")
    borrowed.run_turn("hello", session_key="voice")
    borrowed.clear_session("voice")

    assert calls == [
        ("warm", {"session_key": "voice", "system_prompt": "brief"}),
        ("chatbot", "hello", "voice"),
        ("clear", "voice"),
    ]


def test_window_builds_four_sections_and_all_required_controls(qapp) -> None:
    ctx = SimpleNamespace(core=SimpleNamespace(runtime=object()))
    window = MultimodalWindow(ctx, engine_factory=_StubEngine)
    try:
        groups = {group.title() for group in window.findChildren(QGroupBox)}
        assert groups == {
            "INPUT",
            "AGENT — interaction log",
            "TELEMETRY",
            "AGENTIC WORKSPACE",
        }
        assert set(window.telemetry_rows) == {
            "Wake phrase",
            "Wake",
            "Mode",
            "Model",
            "Microphone",
            "Gate",
            "Audio",
            "Barge",
            "Agent",
            "Output",
            "Endpoint",
            "Now",
        }
        assert set(window.latency_rows) == {
            "Speech detected",
            "End-of-turn",
            "Reply ready",
            "Spoken",
        }
        assert window.mode_box.count() == 3
        assert window.current_audio_mode() == "structured"
        assert window.current_barge_mode() == "stop"
        assert window.current_agentic_tools() is True
        assert window.agentic_check.text() == "Mode: Agentic"
        window.agentic_check.click()
        assert window.current_agentic_tools() is False
        assert window.agentic_check.text() == "Mode: Chatbot"
        assert "tool execution is disabled" in window.reasoning_activity.toPlainText()
        assert set(window.workspace_rows) == {
            "Tasks",
            "Task elapsed",
            "Reply latency",
            "Tools",
            "Tool time",
            "Agent/model",
        }
        assert window.typed_edit.placeholderText().endswith("no wake phrase")
    finally:
        window._main_surface = True
        window.close()


def test_agentic_workspace_renders_activity_tools_outputs_and_artifacts(qapp) -> None:
    ctx = SimpleNamespace(core=SimpleNamespace(runtime=object()))
    window = MultimodalWindow(ctx, engine_factory=_StubEngine)
    try:
        window._on_commit(1, "user", "make a report")
        window._on_agent_event(
            SimpleNamespace(
                topic="/sense/activity",
                kind="thinking",
                text="planning the requested report",
                session="multimodal",
            )
        )
        window._on_agent_event(
            SimpleNamespace(
                topic="/sense/tool",
                name="write_file",
                phase="start",
                detail="",
                elapsed_s=0.0,
                session="multimodal",
            )
        )
        window._on_agent_event(
            SimpleNamespace(
                topic="/sense/tool",
                name="write_file",
                phase="done",
                detail="",
                elapsed_s=0.42,
                session="multimodal",
            )
        )
        window._on_agent_event(
            SimpleNamespace(
                topic="/sense/tool",
                name="write_file",
                phase="output",
                detail='{"path": "/tmp/report.md", "bytes": 120}',
                elapsed_s=0.42,
                session="multimodal",
            )
        )
        window._on_agent_event(
            SimpleNamespace(
                topic="/sense/activity",
                kind="artifact",
                text="/tmp/report.md",
                session="multimodal",
            )
        )
        window._on_latency("Reply ready", 1843.0)
        window._task_started_at = time.monotonic() - 2.0
        window._on_commit(2, "assistant", "done")
        window._on_output_decision(
            "TEXT+SPEECH",
            {"channels": ("text", "speech"), "source": "model-output-directive"},
        )

        assert "planning the requested report" in window.reasoning_activity.toPlainText()
        assert "write_file · 0.42 s" in window.tool_chain.toPlainText()
        assert "/tmp/report.md" in window.tool_outputs.toPlainText()
        assert "/tmp/report.md" in window.artifacts.toPlainText()
        assert window.workspace_rows["Tasks"].text() == "1"
        assert window.workspace_rows["Tools"].text() == "1"
        assert window.workspace_rows["Tool time"].text() == "0.42 s"
        assert window.workspace_rows["Reply latency"].text() == "1,843 ms"
        assert window.telemetry_rows["Output"].text() == "TEXT+SPEECH"
        assert "model-output-directive" in window.reasoning_activity.toPlainText()
    finally:
        window._main_surface = True
        window.close()


def test_agentic_workspace_ignores_another_sessions_events(qapp) -> None:
    ctx = SimpleNamespace(core=SimpleNamespace(runtime=object()))
    window = MultimodalWindow(ctx, engine_factory=_StubEngine)
    try:
        window._on_agent_event(
            SimpleNamespace(
                topic="/sense/activity",
                kind="thinking",
                text="belongs elsewhere",
                session="another-window",
            )
        )
        assert "belongs elsewhere" not in window.reasoning_activity.toPlainText()
    finally:
        window._main_surface = True
        window.close()


def test_preflight_table_exit_code_tracks_failures(capsys) -> None:
    assert print_preflight([Check("engine", True, "1.2.0")]) == 0
    assert "PASS" in capsys.readouterr().out
    assert print_preflight([Check("camera", False, "not found")]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_manifests_index_multimodal_as_face_and_dedicated_app() -> None:
    repo = Path(__file__).resolve().parents[5]
    windowed = load_manifest(repo / "jaeger.windowed.toml")
    dedicated = load_manifest(repo / "jaeger.multimodal.toml")
    windowed_face = next(surface for surface in windowed.surfaces if surface.id == "multimodal")
    assert windowed.version == "0.12.0"
    assert windowed_face.main is False
    assert dedicated.version == "0.12.0"
    assert [(surface.id, surface.main) for surface in dedicated.surfaces] == [
        ("multimodal", True)
    ]
