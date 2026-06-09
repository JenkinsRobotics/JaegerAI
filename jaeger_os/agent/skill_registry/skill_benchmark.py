"""Per-skill benchmarking.

The repo benchmark (``benchmarks/levels/``) measures the *framework*.
This measures a single *skill* — same principle, smaller scope. It
turns skill self-improvement into something measurable: build v2, run
its benchmark, compare to v1's score, keep the better one.

A skill carries its benchmark alongside its smoke test:

    skills/<name>_v<N>/
      SKILL.md
      <code>
      tests/
        smoke_test.py     ← pass/fail gate (loader runs this)
        benchmark.py      ← scored evaluation (this module runs this)
        benchmark_history.jsonl   ← appended every run

``benchmark.py`` is a plain script. When run it prints ONE JSON object
to stdout:

    {"score": 0.0-1.0, "passed": int, "total": int,
     "cases": [{"name": ..., "ok": bool, ...}], "notes": "..."}

``benchmark_skill`` runs it, records the result to history, and reports
the delta vs. the previous run — the signal the agent uses to decide
whether a revision actually improved the skill.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from jaeger_os.agent.skill_registry.skill_package import find_skill_dir


_BENCH_TIMEOUT_S = 120


def _append_history(history_path: Path, entry: dict[str, Any]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _previous_score(history_path: Path) -> float | None:
    """The score from the most recent prior run, or None when this is
    the first benchmark of the skill."""
    if not history_path.is_file():
        return None
    prior: float | None = None
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row.get("score"), (int, float)):
                prior = float(row["score"])
        except Exception:  # noqa: BLE001
            continue
    return prior


def benchmark_skill(layout: Any, skill_name: str) -> dict[str, Any]:
    """Run a skill's ``tests/benchmark.py`` and score it.

    Returns ``{ok, skill, score, passed, total, delta, previous_score,
    cases, ...}``. ``delta`` is the change vs. the previous run — the
    agent reads it to know whether a revision helped. Never raises.
    """
    skill_dir = find_skill_dir(layout, skill_name)
    if skill_dir is None:
        return {"ok": False, "skill": skill_name,
                "error": f"no skill folder {skill_name!r} under {layout.skills_dir}"}

    bench_path = skill_dir / "tests" / "benchmark.py"
    if not bench_path.is_file():
        return {
            "ok": False,
            "skill": skill_name,
            "error": ("no tests/benchmark.py — a benchmark is a script that "
                      "prints one JSON object with a 'score'. See "
                      "docs/skill_template/tests/benchmark.py for the template."),
        }

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(bench_path)],
            capture_output=True, text=True, timeout=_BENCH_TIMEOUT_S,
            cwd=str(skill_dir),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "skill": skill_name,
                "error": f"benchmark timed out after {_BENCH_TIMEOUT_S}s"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "skill": skill_name,
                "error": f"benchmark failed to launch: {exc}"}
    elapsed = time.perf_counter() - started

    if proc.returncode != 0:
        return {
            "ok": False,
            "skill": skill_name,
            "error": f"benchmark exited {proc.returncode}",
            "stderr": (proc.stderr or "")[-2000:],
        }

    # The benchmark prints one JSON object. Take the last JSON-looking
    # line so stray prints before it don't break parsing.
    parsed: dict[str, Any] | None = None
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if parsed is None:
        return {
            "ok": False,
            "skill": skill_name,
            "error": "benchmark produced no parseable JSON result",
            "stdout": (proc.stdout or "")[-2000:],
        }

    score = float(parsed.get("score", 0.0) or 0.0)
    passed = int(parsed.get("passed", 0) or 0)
    total = int(parsed.get("total", 0) or 0)

    history_path = skill_dir / "tests" / "benchmark_history.jsonl"
    previous = _previous_score(history_path)
    delta = (score - previous) if previous is not None else None

    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "skill": skill_name,
        "skill_folder": skill_dir.name,
        "score": round(score, 4),
        "passed": passed,
        "total": total,
        "elapsed_s": round(elapsed, 3),
    }
    _append_history(history_path, record)

    # 0.3.0: also route the result into v3 capability state when the
    # skill has a manifest (or a stub).  ``record_benchmark_result``
    # finds the manifest, picks the right capability (explicit
    # ``cap`` field on the benchmark payload, or the single capability
    # if the manifest only declares one), and updates state.yaml +
    # history.jsonl with promotion/demotion applied.  Never raises;
    # legacy paths that don't have v3 plumbing still see the existing
    # benchmark_history.jsonl behaviour above.
    cap_result: dict[str, Any] = {}
    try:
        from jaeger_os.agent.skill_registry.capability_state import record_benchmark_result
        cap_result = record_benchmark_result(
            skill_folder=skill_dir,
            benchmark_payload=parsed,
        )
    except Exception as exc:  # noqa: BLE001
        cap_result = {"ok": False, "reason": f"capability state error: {exc}"}

    return {
        "ok": True,
        "skill": skill_name,
        "skill_folder": skill_dir.name,
        "score": round(score, 4),
        "passed": passed,
        "total": total,
        "previous_score": (round(previous, 4) if previous is not None else None),
        "delta": (round(delta, 4) if delta is not None else None),
        "improved": (delta is not None and delta > 0),
        "elapsed_s": round(elapsed, 3),
        "cases": parsed.get("cases", []),
        "notes": parsed.get("notes", ""),
        "capability": cap_result,    # v3: {ok, cap, level, delta, runs_total}
    }
