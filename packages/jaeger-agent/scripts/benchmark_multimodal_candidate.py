#!/usr/bin/env python3
"""Run VoiceLLM's neutral multimodal benchmark through AgentRuntime."""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

# Keep the agentic surface available through load_tools while avoiding a
# 100-schema prompt on every elementary benchmark question.
os.environ.setdefault("JAEGER_TOOLSET_SCOPING", "1")


def _load_benchmark(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "voicellm_multimodal_benchmark", path / "benchmark_multimodal.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load benchmark from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _read_wav(path: Path) -> np.ndarray:
    import soundfile as sf

    audio, sample_rate = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio[:, 0]
    if sample_rate != 16_000:
        old = np.arange(audio.size, dtype=np.float64)
        new = np.linspace(
            0, max(0, audio.size - 1), int(audio.size * 16_000 / sample_rate)
        )
        audio = np.interp(new, old, audio).astype(np.float32)
    return np.asarray(audio, dtype=np.float32)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[float, Any]] = []
        self.started = 0.0
        self.spoken_text = ""

    def reset(self) -> None:
        self.events = []
        self.started = time.perf_counter()
        self.spoken_text = ""

    def __call__(self, event: Any) -> None:
        self.events.append((time.perf_counter(), event))

    def result(self, case: dict[str, Any], modality: str, error: Any = None) -> dict:
        assistant_events = [
            event for _, event in self.events if event.kind == "assistant"
        ]
        assistant = [event.text for event in assistant_events]
        output_data = (
            assistant_events[-1].data
            if assistant_events and isinstance(assistant_events[-1].data, dict)
            else {}
        )
        live = [
            event.text
            for _, event in self.events
            if event.kind == "live" and event.text and not event.text.endswith(" ▌")
        ]
        audio = [
            np.asarray(event.data).reshape(-1)
            for _, event in self.events
            if event.kind == "audio" and event.data is not None
        ]
        first_audio = next(
            (stamp for stamp, event in self.events if event.kind == "audio"), None
        )
        return {
            "id": case["id"],
            "modality": modality,
            # Dynamic output can deliberately leave the display channel blank
            # while speaking the semantic answer. Score what the user received,
            # regardless of which engine-owned output channel carried it.
            "response": (assistant[-1] if assistant and assistant[-1]
                         else self.spoken_text),
            "transcript": live[0] if modality == "spoken" and live else None,
            "total_ms": round((time.perf_counter() - self.started) * 1000, 2),
            "first_audio_ms": (
                round((first_audio - self.started) * 1000, 2)
                if first_audio is not None
                else None
            ),
            "audio_samples": sum(chunk.size for chunk in audio),
            "audio_rate": 24_000,
            "output_channels": list(output_data.get("channels") or ()),
            "output_source": output_data.get("source"),
            "error": str(error) if error else None,
        }


def run(args: argparse.Namespace, *, engine_factory: Any = None) -> dict[str, Any]:
    from jaeger_agent import MultimodalAgent, __version__
    from jaeger_agent.core.policy import SYSTEM_PROMPT

    benchmark = _load_benchmark(args.benchmark_dir)
    cases = json.loads((args.benchmark_dir / "cases.json").read_text())
    wanted = {item.strip() for item in (args.ids or "").split(",") if item.strip()}

    def selected(case: dict[str, Any]) -> bool:
        return not wanted or case["id"] in wanted

    benchmark.prepare_assets()
    recorder = Recorder()
    runtime_config = {
        "provider": "llama_cpp",
        "model_path": str(args.model_path),
        "ctx": args.ctx,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "tools_enabled": args.agentic_tools,
    }
    engine = (engine_factory or MultimodalAgent)(
        on_event=recorder,
        want_vision=True,
        play=False,
        audio_mode="plain",
        output_mode="dynamic" if args.agentic_tools else "speech",
        runtime_config=runtime_config,
    )
    synthesize = engine._speak

    def record_and_synthesize(text: str) -> None:
        recorder.spoken_text = text
        synthesize(text)

    engine._speak = record_and_synthesize

    load_started = time.perf_counter()
    engine.load()
    runtime = engine.node_llm.runtime
    warm_key = engine.node_llm.session_key
    if callable(getattr(runtime, "agent_for", None)):
        warm_agent = runtime.agent_for(warm_key, system_prompt=SYSTEM_PROMPT)
        visible_tools = len(warm_agent.tools)
        available_tools = len(warm_agent.all_tools)
    else:
        # An attached application runtime owns its registry in another process.
        # Do not invent counts or load a second agent just to inspect them.
        visible_tools = available_tools = None
    engine.node_llm.clear()
    load_ms = (time.perf_counter() - load_started) * 1000
    rows: list[dict[str, Any]] = []

    def reset_case() -> None:
        engine.node_llm.clear()

    def capture(case: dict[str, Any], modality: str, action: Any) -> None:
        reset_case()
        recorder.reset()
        error = None
        try:
            action()
        except Exception as exc:  # every failed case remains in the result
            error = f"{type(exc).__name__}: {exc}"
        row = recorder.result(case, modality, error)
        rows.append(row)
        mark = "DONE" if error is None else "ERROR"
        print(
            f"  {mark:<5} {case['id']:<28} {row['total_ms']:>9.0f} ms  "
            f"{row['response'][:70]}",
            flush=True,
        )

    try:
        for case in filter(selected, cases["text"]):
            capture(case, "text", lambda item=case: engine.send_text(item["prompt"]))

        for case in filter(selected, cases["memory"]):
            reset_case()
            engine.send_text(case["setup"])
            recorder.reset()
            error = None
            try:
                engine.send_text(case["prompt"])
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            rows.append(recorder.result(case, "memory", error))

        for case in filter(selected, cases["vision"]):
            asset_name = case["asset"].split(":", 1)[1]
            uri = _data_uri(args.benchmark_dir / "assets" / f"{asset_name}.png")
            capture(
                case,
                "vision",
                lambda item=case, image=uri: (
                    engine.attach_image(image),
                    engine.send_text(item["prompt"]),
                ),
            )

        for case in filter(selected, cases["spoken"]):
            wav = args.audio_dir / case["wav"]
            if not wav.is_file():
                rows.append(
                    {
                        "id": case["id"],
                        "modality": "spoken",
                        "response": "",
                        "transcript": None,
                        "total_ms": None,
                        "first_audio_ms": None,
                        "audio_samples": 0,
                        "audio_rate": 24_000,
                        "error": f"missing fixture: {wav}",
                    }
                )
                continue
            audio = _read_wav(wav)

            def spoken_action(samples: np.ndarray = audio) -> None:
                engine._started = time.time()
                engine._followup_deadline = time.time() + 60
                engine._on_turn(samples)

            capture(case, "spoken", spoken_action)
    finally:
        engine.close()

    result = {
        "schema": "multimodal-agent-result-v1",
        "benchmark": cases["benchmark"],
        "engine": "jaeger-agent-agentruntime",
        "suite": "full" if not wanted else "selected",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "load_ms": round(load_ms, 2),
        "cases": rows,
        "configuration": {
            "model": str(args.model_path),
            "model_precision": "Q4_K_M",
            "audio_mode": "plain",
            "play": False,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "ctx": args.ctx,
            "agentic_tools": args.agentic_tools,
            "toolset_scoping": True,
            "selected_ids": sorted(wanted),
            "visible_tools": visible_tools,
            "available_tools": available_tools,
            "memory_owner": "AgentRuntime",
            "audio_output": "synthesized Kokoro af_heart PCM at 24000 Hz",
        },
        "environment": {
            "jaeger_agent": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ctx", type=int, default=8192)
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--ids",
        default="",
        help="optional comma-separated case ids; empty runs the full suite",
    )
    parser.add_argument(
        "--agentic-tools",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="use AgentRuntime tools; --no-agentic-tools benchmarks chatbot mode",
    )
    args = parser.parse_args()
    result = run(args)
    errors = sum(bool(row.get("error")) for row in result["cases"])
    print(f"\nRaw result: {args.output}")
    print(f"Cases: {len(result['cases'])}; errors: {errors}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
