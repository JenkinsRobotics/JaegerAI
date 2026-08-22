#!/usr/bin/env python3
"""Master Comprehensive Agentic Test Suite for JaegerAI.

Validates:
  1. All Native Tool Families (Filesystem, Code Execution, Memory/Recall, Math/Time, Web, Audio, Kanban/Board, Schedules, Automation).
  2. All Connected MCP Server Tools (e.g. mcp__ares-native__notes_operations, reminders, calendar).
  3. Long-Duration & Multi-Step Autonomous Chains (multi-step pipelines, error recovery, context resilience).

Usage:
  python dev/benchmark/master_agentic_eval.py                     # Run full master test on active model
  python dev/benchmark/master_agentic_eval.py --quick             # Fast multi-category sanity test
  python dev/benchmark/master_agentic_eval.py --category native   # Test all native tools
  python dev/benchmark/master_agentic_eval.py --category mcp      # Test all MCP tools
  python dev/benchmark/master_agentic_eval.py --category long_task# Test long-duration autonomous chaining
  python dev/benchmark/master_agentic_eval.py --models ollama-cloud:qwen3.5:397b,ollama-cloud:gemma4:31b
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any

# Ensure repo root is on sys.path
_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
os.chdir(_REPO)

from jaeger_ai.core.bench.cases import BenchCase
from jaeger_ai.core.bench.scenarios import build_hermetic_instance
from jaeger_ai.core.instance.instance import resolve_instance_dir


MASTER_CASES: list[BenchCase] = [
    # ── 1. NATIVE TOOLS: MATH & TIME ──────────────────────────────
    BenchCase(
        id="native_time_local",
        prompt="what time is it right now?",
        expected_tools=["get_time"],
        tags=["native", "time", "routing"],
    ),
    BenchCase(
        id="native_time_timezone",
        prompt="what is the current time in Tokyo?",
        expected_tools=["get_time"],
        tags=["native", "time", "routing"],
    ),
    BenchCase(
        id="native_math_arithmetic",
        prompt="calculate 849 times 324 plus 157",
        expected_tools=["calculate"],
        answer_contains_any=["275233"],
        tags=["native", "math", "routing"],
    ),
    BenchCase(
        id="native_math_sqrt",
        prompt="what is the square root of 98765?",
        expected_tools=["calculate"],
        answer_contains_any=["314.269", "314.26", "314.27", "314.3"],
        tags=["native", "math", "routing"],
    ),

    # ── 2. NATIVE TOOLS: FILESYSTEM ───────────────────────────────
    BenchCase(
        id="native_file_write",
        prompt="create a file in workspace named master_test.txt containing 'agentic master test payload 2026'",
        expected_tools=["write_file"],
        tags=["native", "files", "routing"],
    ),
    BenchCase(
        id="native_file_read",
        prompt="read the contents of master_test.txt from workspace",
        expected_tools=["read_file"],
        answer_contains_any=["agentic master test payload 2026"],
        tags=["native", "files", "routing"],
    ),
    BenchCase(
        id="native_file_search",
        prompt="search the workspace for files containing 'payload 2026'",
        expected_tools=["search_files", "list_skill_dir", "read_file"],
        tags=["native", "files", "search"],
    ),
    BenchCase(
        id="native_file_delete",
        prompt="delete the file master_test.txt from workspace",
        expected_tools=["delete_file"],
        tags=["native", "files", "cleanup"],
    ),

    # ── 3. NATIVE TOOLS: COGNITION & MEMORY ───────────────────────
    BenchCase(
        id="native_memory_store",
        session="master_mem_sess",
        prompt="remember that my primary production server is located in us-west-2 and is named 'titan-01'",
        expected_tools=["remember", "memory"],
        tags=["native", "memory", "cognition"],
    ),
    BenchCase(
        id="native_memory_recall",
        session="master_mem_sess",
        prompt="where is my primary production server located and what is its name?",
        expected_tools=["recall", "search_memory", "memory"],
        answer_contains_all=["titan-01", "us-west-2"],
        tags=["native", "memory", "cognition"],
    ),
    BenchCase(
        id="native_memory_facts",
        session="master_mem_sess",
        prompt="list all facts you currently have recorded about me in memory",
        expected_tools=["list_facts", "memory"],
        tags=["native", "memory", "cognition"],
    ),

    # ── 4. NATIVE TOOLS: CODE EXECUTION & TERMINAL ────────────────
    BenchCase(
        id="native_code_python",
        prompt="run a python snippet to compute sum(x**2 for x in range(1, 11)) and return the result",
        expected_tools=["execute_code", "run_python", "calculate"],
        answer_contains_any=["385"],
        tags=["native", "code", "execution"],
    ),
    BenchCase(
        id="native_code_terminal",
        prompt="run a terminal command to echo 'JAEGER_MASTER_TEST_OK'",
        expected_tools=["terminal", "execute_code"],
        answer_contains_any=["JAEGER_MASTER_TEST_OK"],
        tags=["native", "code", "terminal"],
    ),

    # ── 5. NATIVE TOOLS: WEB & WEATHER ────────────────────────────
    BenchCase(
        id="native_web_weather",
        prompt="what is the current weather forecast for San Francisco?",
        expected_tools=["get_weather", "web_search"],
        tags=["native", "web", "weather"],
    ),
    BenchCase(
        id="native_web_search",
        prompt="search the web for the official launch year of Python",
        expected_tools=["web_search", "web_extract"],
        answer_contains_any=["1991"],
        tags=["native", "web", "search"],
    ),

    # ── 6. NATIVE TOOLS: TASK TRACKER (KANBAN/BOARD) & SCHEDULING ──
    BenchCase(
        id="native_board_add",
        session="master_board_sess",
        prompt="add a task card to the board: 'Review Agentic Architecture' in todo column",
        expected_tools=["board_add", "kanban", "board_update"],
        tags=["native", "board", "task"],
    ),
    BenchCase(
        id="native_board_view",
        session="master_board_sess",
        prompt="view the current task board cards",
        expected_tools=["board_view", "kanban"],
        answer_contains_any=["Review Agentic Architecture"],
        tags=["native", "board", "task"],
    ),
    BenchCase(
        id="native_schedule_prompt",
        prompt="schedule a prompt every day at 9am to summarize open pull requests",
        expected_tools=["schedule_prompt"],
        tags=["native", "schedule"],
    ),

    # ── 7. MCP TOOLS: NOTES, REMINDERS & CALENDAR ─────────────────
    BenchCase(
        id="mcp_notes_operation",
        prompt="search my Apple Notes for any notes mentioning 'Hermes' or 'LLM'",
        expected_tools=["mcp__ares-native__notes_operations", "notes", "notes_operations"],
        tags=["mcp", "notes", "macos"],
    ),
    BenchCase(
        id="mcp_reminders_operation",
        prompt="check my Apple Reminders for tasks due today",
        expected_tools=["mcp__ares-native__reminders_operations", "reminders", "get_events"],
        tags=["mcp", "reminders", "macos"],
    ),
    BenchCase(
        id="mcp_calendar_operation",
        prompt="list all calendar events scheduled on my calendar for this week",
        expected_tools=["mcp__ares-native__calendar_operations", "get_events", "calendar"],
        tags=["mcp", "calendar", "macos"],
    ),

    # ── 8. LONG-DURATION AUTONOMOUS CHAINING ──────────────────────
    BenchCase(
        id="long_task_5step_pipeline",
        session="long_task_sess",
        prompt=(
            "Execute this multi-step pipeline: "
            "1. Calculate 125 * 64. "
            "2. Write the computed result into workspace file 'pipeline_result.txt'. "
            "3. Read back the file to verify the content. "
            "4. Remember a fact 'last_pipeline_val' with that computed number. "
            "5. Report the final verified number."
        ),
        expected_tools=["calculate", "write_file", "read_file", "remember", "memory"],
        answer_contains_any=["8000"],
        tags=["long_task", "multistep", "autonomous"],
    ),
    BenchCase(
        id="long_task_batch_resilience",
        session="long_task_sess",
        prompt=(
            "Check what was saved in 'last_pipeline_val' from memory, "
            "then delete 'pipeline_result.txt' from workspace and confirm completion."
        ),
        expected_tools=["recall", "memory", "delete_file"],
        answer_contains_any=["8000"],
        tags=["long_task", "multistep", "recovery"],
    ),
]


def run_master_eval(
    *,
    cases: list[BenchCase],
    model_target: str | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Execute the master agentic benchmark and return performance telemetry."""
    from jaeger_ai.core.bench.scenarios import build_hermetic_instance
    from dev.benchmark.bench import _prepared_config
    from jaeger_ai.main import boot_for_tui, _run_turn

    live_dir = pathlib.Path(resolve_instance_dir(None))
    results: list[dict[str, Any]] = []
    category_stats: dict[str, dict[str, int]] = {}

    print(f"\n{'='*70}")
    print(f"=== Running Master Agentic Benchmark ({len(cases)} cases) ===")
    if model_target:
        print(f"Target Model: {model_target}")
    print(f"{'='*70}\n")

    with _prepared_config(model_target=model_target, force_allow=True, hermetic=True):
        boot = boot_for_tui(warmup=False)
        client = boot.client

        for i, case in enumerate(cases):
            session_key = case.session or f"master_case_{case.id}_{i}"
            started = time.perf_counter()
            out = _run_turn(client, case.prompt, session_key=session_key)
            duration = time.perf_counter() - started

            tools_called = [
                line.strip().split("(")[0].replace("▸", "").strip()
                for line in out.get("tool_activity", [])
                if line.strip()
            ]

            # Evaluate assertions
            passed = True
            failure_reasons = []

            # 1. Expected tools check (supports MCP alias equivalence)
            if case.expected_tools:
                called_set = set(tools_called)
                from jaeger_ai.core.bench.cases import UMBRELLA_EQUIVALENTS
                normalized_called = set(tools_called)
                for c in tools_called:
                    if c.startswith("mcp__ares-native__"):
                        normalized_called.add(c.replace("mcp__ares-native__", ""))
                        normalized_called.add(c.replace("mcp__ares-native__", "").split("_")[0])

                matched = False
                for exp in case.expected_tools:
                    if exp in normalized_called:
                        matched = True
                        break
                    if exp in UMBRELLA_EQUIVALENTS:
                        if UMBRELLA_EQUIVALENTS[exp] & called_set:
                            matched = True
                            break

                if not matched and tools_called:
                    matched = any(exp in " ".join(tools_called) for exp in case.expected_tools)

                if not matched:
                    passed = False
                    failure_reasons.append(f"Expected tool in {case.expected_tools}, called {tools_called}")

            # 2. Text assertions
            answer_text = (out.get("text") or "").lower()
            if case.answer_contains_any:
                if not any(k.lower() in answer_text for k in case.answer_contains_any):
                    passed = False
                    failure_reasons.append(f"Answer missing any of {case.answer_contains_any}")

            if case.answer_contains_all:
                if not all(k.lower() in answer_text for k in case.answer_contains_all):
                    passed = False
                    failure_reasons.append(f"Answer missing all of {case.answer_contains_all}")

            # Record stats
            for tag in case.tags:
                stat = category_stats.setdefault(tag, {"passed": 0, "total": 0})
                stat["total"] += 1
                if passed:
                    stat["passed"] += 1

            status_mark = "✓ PASS" if passed else "✗ FAIL"
            print(f"[{i+1:02d}/{len(cases):02d}] {case.id:<30} {status_mark:<8} ({duration:.2f}s) | tools={tools_called}")
            if not passed and verbose and failure_reasons:
                print(f"       Reason: {'; '.join(failure_reasons)}")

            results.append({
                "id": case.id,
                "passed": passed,
                "duration_s": round(duration, 2),
                "tools_called": tools_called,
                "reasons": failure_reasons,
                "tags": case.tags,
            })

    total_passed = sum(1 for r in results if r["passed"])
    pass_pct = (total_passed / len(results)) * 100 if results else 0.0
    avg_lat = sum(r["duration_s"] for r in results) / len(results) if results else 0.0

    print(f"\n{'-'*70}")
    print(f"Master Agentic Test Result: {total_passed}/{len(results)} Passed ({pass_pct:.1f}%) | Avg Latency: {avg_lat:.2f}s")
    print(f"{'-'*70}")
    print("Breakdown by Category:")
    for tag, stat in sorted(category_stats.items()):
        tag_pct = (stat["passed"] / stat["total"]) * 100 if stat["total"] else 0.0
        print(f"  • {tag:<15}: {stat['passed']}/{stat['total']} ({tag_pct:.1f}%)")

    return {
        "model": model_target or "active",
        "passed": total_passed,
        "total": len(results),
        "pass_pct": round(pass_pct, 1),
        "avg_latency": round(avg_lat, 2),
        "categories": category_stats,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Master Comprehensive Agentic Benchmark")
    parser.add_argument("--quick", action="store_true", help="Run quick sanity subset")
    parser.add_argument("--category", type=str, default="", help="Filter by tag (native, mcp, long_task, etc.)")
    parser.add_argument("--model", type=str, default=None, help="Target model (e.g. ollama-cloud:qwen3.5:397b)")
    parser.add_argument("--models", type=str, default="", help="Comma-separated model list for comparison sweep")
    args = parser.parse_args()

    cases = MASTER_CASES
    if args.category:
        cats = [c.strip().lower() for c in args.category.split(",")]
        cases = [c for c in cases if any(cat in c.tags for cat in cats)]

    if args.quick:
        selected_tags = ["time", "math", "files", "memory", "code", "web", "board", "mcp", "long_task"]
        quick_cases = []
        for t in selected_tags:
            matching = [c for c in cases if t in c.tags]
            if matching:
                quick_cases.append(matching[0])
        cases = quick_cases

    if args.models:
        model_list = [m.strip() for m in args.models.split(",") if m.strip()]
        leaderboard = []
        for m in model_list:
            res = run_master_eval(cases=cases, model_target=m)
            leaderboard.append(res)

        print("\n# Master Multi-Model Comparison Leaderboard")
        print("| Model | Pass Rate | Passed / Total | Avg Latency |")
        print("|---|---|---|---|")
        for row in leaderboard:
            print(f"| `{row['model']}` | **{row['pass_pct']}%** | {row['passed']}/{row['total']} | {row['avg_latency']}s |")
    else:
        run_master_eval(cases=cases, model_target=args.model)


if __name__ == "__main__":
    main()
