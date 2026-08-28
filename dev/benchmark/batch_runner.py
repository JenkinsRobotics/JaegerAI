"""Batch trajectory and scenario runner for JaegerAI.

The runner boots the real JaegerAI pipeline once, gives every scenario its
own session, and writes one JSON object per completed scenario. A ``turn_fn``
can be injected by tests or embedding applications to avoid booting a model.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TurnFn = Callable[[str, str], str]


def run_batch_scenarios(
    scenarios: list[dict[str, str]],
    output_jsonl: Path | None = None,
    *,
    turn_fn: TurnFn | None = None,
) -> list[dict[str, Any]]:
    """Run scenarios and return their result trajectories.

    With no ``turn_fn``, use the same product boot and turn path as the CLI
    instead of constructing the core loop without its required adapter.
    """
    boot = None
    if turn_fn is None:
        from jaeger_ai.main import _run_turn, boot_for_tui

        boot = boot_for_tui(instance_name=None, with_memory=True, warmup=False)

        def _product_turn(prompt: str, session_key: str) -> str:
            out = _run_turn(boot.client, prompt, session_key=session_key)
            return str(out.get("text") or out.get("answer") or "")

        turn_fn = _product_turn

    if output_jsonl is not None:
        output_jsonl = output_jsonl.expanduser().resolve()
        output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    try:
        for idx, scenario in enumerate(scenarios, 1):
            prompt = str(scenario.get("prompt") or "")
            name = str(scenario.get("name") or f"scenario_{idx}")
            logger.info("Running scenario %d/%d: %r", idx, len(scenarios), name)

            started = time.perf_counter()
            try:
                reply = turn_fn(prompt, f"batch-eval-{idx}")
                result: dict[str, Any] = {
                    "name": name,
                    "prompt": prompt,
                    "response": reply,
                    "status": "success",
                    "duration_s": round(time.perf_counter() - started, 3),
                }
            except Exception as exc:  # noqa: BLE001 -- record and continue corpus
                result = {
                    "name": name,
                    "prompt": prompt,
                    "error": f"{type(exc).__name__}: {exc}",
                    "status": "failed",
                    "duration_s": round(time.perf_counter() - started, 3),
                }
            results.append(result)

            if output_jsonl is not None:
                with output_jsonl.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    finally:
        if boot is not None:
            with contextlib.suppress(Exception):
                boot.cleanup()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="JaegerAI batch trajectory runner")
    parser.add_argument(
        "--input-json", type=Path, required=True,
        help="JSON file containing a list of scenarios",
    )
    parser.add_argument(
        "--output-jsonl", type=Path, required=True,
        help="JSONL destination for trajectories",
    )
    args = parser.parse_args()

    with args.input_json.open("r", encoding="utf-8") as handle:
        scenarios = json.load(handle)
    if not isinstance(scenarios, list):
        parser.error("--input-json must contain a JSON list")

    results = run_batch_scenarios(scenarios, args.output_jsonl)
    failures = sum(row["status"] != "success" for row in results)
    print(
        f"Batch completed: {len(results) - failures} passed, {failures} failed; "
        f"results saved to {args.output_jsonl}"
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
