"""Benchmark template for example_v1 — the scored-evaluation pattern.

A benchmark sits beside the smoke test. The smoke test is a pass/fail
gate ("does the skill basically work"). The benchmark is a *scored*
evaluation that ``benchmark_skill`` runs to track improvement across
revisions — same idea as the repo's level benchmarks, scoped to one
skill.

Contract: when run, print exactly ONE JSON object to stdout with:

    {"score": 0.0-1.0,           # overall — passed / total, or weighted
     "passed": int,
     "total": int,
     "cases": [{"name": str, "ok": bool, ...}],   # per-case detail
     "notes": str}               # optional, free-text

Keep it fast (under ~2 minutes). When you author a new skill, copy
this file into its ``tests/`` and replace the cases with real ones.
"""

import importlib.util
import json
import sys
from pathlib import Path


def _load_skill_module():
    """Import the skill's module so the benchmark can call into it."""
    spec = importlib.util.spec_from_file_location(
        "example", Path(__file__).resolve().parent.parent / "example.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = _load_skill_module()
    cases = []

    # Case 1 — named greeting
    out = mod.say_example("jaeger")
    cases.append({
        "name": "named_greeting",
        "ok": out == {"greeting": "Hello, jaeger!", "skill": "example_v1"},
        "got": out,
    })

    # Case 2 — default argument
    out = mod.say_example()
    cases.append({
        "name": "default_greeting",
        "ok": out.get("greeting") == "Hello, world!",
        "got": out,
    })

    # Case 3 — whitespace-only input falls back to "world"
    out = mod.say_example("   ")
    cases.append({
        "name": "blank_falls_back",
        "ok": out.get("greeting") == "Hello, world!",
        "got": out,
    })

    passed = sum(1 for c in cases if c["ok"])
    total = len(cases)
    result = {
        "score": round(passed / total, 4) if total else 0.0,
        "passed": passed,
        "total": total,
        "cases": cases,
        "notes": "Reference benchmark — copy this file when authoring a skill.",
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
