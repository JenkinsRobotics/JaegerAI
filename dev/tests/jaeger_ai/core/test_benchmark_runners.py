"""Regression tests for the standalone benchmark entry points."""

from __future__ import annotations

import json

from dev.benchmark.batch_runner import run_batch_scenarios
from dev.benchmark.swe_runner import run_swe_benchmark_task


def test_batch_runner_uses_injected_turn_and_writes_jsonl(tmp_path):
    destination = tmp_path / "results" / "rows.jsonl"

    def turn(prompt: str, session_key: str) -> str:
        if prompt == "fail":
            raise RuntimeError("expected")
        return f"{session_key}:{prompt}"

    rows = run_batch_scenarios(
        [
            {"name": "one", "prompt": "hello"},
            {"name": "two", "prompt": "fail"},
        ],
        destination,
        turn_fn=turn,
    )

    assert [row["status"] for row in rows] == ["success", "failed"]
    assert rows[0]["response"] == "batch-eval-1:hello"
    persisted = [json.loads(line) for line in destination.read_text().splitlines()]
    assert persisted == rows


def test_swe_runner_uses_injected_turn_and_verifies_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    result = run_swe_benchmark_task(
        repo,
        "write the marker",
        "test -d .",
        turn_fn=lambda prompt: {"text": prompt, "steps": 3},
    )

    assert result["status"] == "passed"
    assert result["turns"] == 3
    assert result["error"] is None


def test_swe_runner_rejects_an_empty_verification_command(tmp_path):
    result = run_swe_benchmark_task(
        tmp_path,
        "noop",
        "  ",
        turn_fn=lambda _prompt: "unused",
    )

    assert result["status"] == "failed"
    assert result["error"] == "Verification command is empty"
