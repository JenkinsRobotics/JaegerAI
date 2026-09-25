"""Headless worker/Event routing contract test."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from .worker import EVENT_KINDS, MultimodalWorker  # noqa: E402


class _StubEngine:
    def __init__(self, **kwargs: Any) -> None:
        self.on_event = kwargs["on_event"]
        self.speaking = SimpleNamespace(is_set=lambda: False)
        self.config = SimpleNamespace(fallback_llm_model_path="stub.gguf")
        self.node_llm = SimpleNamespace(runtime=SimpleNamespace(health=lambda: {"model": "stub"}))
        self.drain_input = lambda: None

    def set_barge_mode(self, _mode: str) -> None:
        return None

    def close(self) -> None:
        return None


def selftest() -> list[tuple[bool, str]]:
    app = QApplication.instance() or QApplication([])
    worker = MultimodalWorker(engine_factory=_StubEngine)
    seen: list[tuple[str, tuple[Any, ...]]] = []
    for name in (
        "commit",
        "output",
        "tscript",
        "telem",
        "status",
        "live",
        "lat",
        "spoke",
        "heard",
    ):
        getattr(worker, name).connect(
            lambda *args, signal=name: seen.append((signal, args))
        )

    samples = np.zeros(4, dtype=np.float32)
    payloads = {
        "user": ("hello", None),
        "assistant": (
            "hi",
            {"display": True, "channels": ("text", "speech"), "source": "test"},
        ),
        "overheard": ("hallway", None),
        "environment": ("(music)", None),
        "self": ("echo", None),
        "submitted": ("[context: speaker=S1]\nhello", None),
        "session": ("Mode", "FOLLOW-UP"),
        "status": ("ready", None),
        "state": ("thinking", None),
        "live": ("form…", None),
        "latency": ("Reply ready", 123.0),
        "audio": ("reply", samples),
        "mic": ("", samples),
    }
    for kind, (text, data) in payloads.items():
        worker._on_event(SimpleNamespace(kind=kind, text=text, data=data))

    signal_names = [name for name, _args in seen]
    checks = [
        (EVENT_KINDS == frozenset(payloads), "every engine Event kind is enumerated"),
        (signal_names.count("commit") == 2, "user/assistant route to interaction commits"),
        (signal_names.count("output") == 1, "output decisions route independently"),
        (signal_names.count("tscript") == 5, "all transcript dispositions route visibly"),
        (signal_names.count("telem") == 2, "session/state route to telemetry"),
        (signal_names.count("status") == 1, "status routes to status line"),
        (signal_names.count("live") == 1, "forming text routes to LIVE"),
        (signal_names.count("lat") == 1, "latency routes to latency rows"),
        (signal_names.count("spoke") == 1, "TTS PCM routes to agent waveform"),
        (signal_names.count("heard") == 1, "engine mic PCM routes to user waveform"),
    ]
    try:
        worker._on_event(SimpleNamespace(kind="future-event", text="", data=None))
    except ValueError:
        loud = True
    else:
        loud = False
    checks.append((loud, "an unknown Event kind fails loudly"))
    del app  # keep the QApplication alive for every signal emission above
    return checks


def main() -> int:
    checks = selftest()
    for passed, description in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {description}")
    failures = sum(not passed for passed, _description in checks)
    print(f"\n{len(checks) - failures}/{len(checks)} checks passed")
    return 1 if failures else 0


__all__ = ["main", "selftest"]
