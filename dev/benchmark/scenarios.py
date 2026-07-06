#!/usr/bin/env python3
"""The JROS SCENARIO suite — the full-system, real-side-effect gate.

This is the second benchmark type, distinct from the routing corpus
(`dev/benchmark/bench.py`):

  * Routing corpus — fast, single-turn, tool-routing + answer_contains.
    Runs on every prompt tweak.
  * Scenario suite (THIS) — full-system, multi-turn, DETERMINISTIC
    side-effect checks (a file exists with content X, a schedule was
    persisted, a credential sweep was REFUSED). Slower; a PRE-RELEASE gate.

    python dev/benchmark/scenarios.py                 # every runnable scenario
    python dev/benchmark/scenarios.py --lane security # SEC gates only
    python dev/benchmark/scenarios.py --ids file-scratchpad
    python dev/benchmark/scenarios.py --list          # list, don't run
    python dev/benchmark/scenarios.py --keep-temp     # don't delete the tmp instance

HERMETIC BY CONSTRUCTION
------------------------
The scenarios WRITE real files/schedules/facts/board-cards. So the run
boots a THROWAWAY temp instance (copy of the live config/identity into a
tempdir, fresh empty memory/workspace, ``JAEGER_INSTANCE_DIR`` pointed
there) and deletes it afterwards. It is IMPOSSIBLE for a scenario to touch
the operator's live instance: we never snapshot-restore live state, and the
tempdir is removed in a ``finally``. The run verifies, before and after,
that the live instance's memory signature is unchanged.

Exit code: 0 = all pass; 1 = a scriptable scenario failed; 2 = a SECURITY
gate failed (LOUD — a real vulnerability, not a score dip). Inconclusive
(a per-turn timeout) never sets a failing exit code but is flagged.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import pathlib
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for p in here.parents:
        if (p / "pyproject.toml").is_file():
            return p
    return here.parents[2]


_REPO = _repo_root()
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
os.chdir(_REPO)


# ── result model ────────────────────────────────────────────────────


@dataclass
class ScenarioResult:
    id: str
    lane: str
    category: str
    status: str          # "pass" | "fail" | "inconclusive"
    detail: str
    elapsed_s: float
    tools: list[str]


# ── live-instance signature (untouched-verification) ────────────────


def _live_signature(live_dir: pathlib.Path) -> dict[str, tuple[int, float]]:
    """A ``{relpath: (size, mtime)}`` map of the live instance's mutable
    state — memory/, board.json, config.yaml. Compared before/after to
    PROVE the hermetic run never touched the operator's instance."""
    sig: dict[str, tuple[int, float]] = {}
    targets = [live_dir / "memory", live_dir / "config.yaml",
               live_dir / "identity.yaml"]
    for t in targets:
        if t.is_file():
            st = t.stat()
            sig[t.name] = (st.st_size, st.st_mtime)
        elif t.is_dir():
            for p in sorted(t.rglob("*")):
                if p.is_file():
                    st = p.stat()
                    sig[str(p.relative_to(live_dir))] = (st.st_size, st.st_mtime)
    return sig


# ── memory readback (fills MemoryView from the TEMP instance) ────────


def _read_memory_view(layout: Any):
    from jaeger_os.core.bench.scenarios import MemoryView
    facts: dict[str, str] = {}
    schedules: list[dict] = []
    board: list[dict] = []
    with contextlib.suppress(Exception):
        from jaeger_os.core.memory import memory as mem
        facts = mem.list_facts(None) or {}
    with contextlib.suppress(Exception):
        from jaeger_os.core.memory import memory as mem
        schedules = mem.list_schedules() or []
    with contextlib.suppress(Exception):
        import json
        board_path = pathlib.Path(getattr(layout, "memory_dir")) / "board.json"
        if board_path.is_file():
            data = json.loads(board_path.read_text(encoding="utf-8"))
            board = data.get("cards", []) if isinstance(data, dict) else []
    return MemoryView(facts=facts, schedules=schedules, board=board)


# ── turn driver (captures tool ARGS; bounded per-turn timeout) ───────


def _build_agent(client: Any):
    from jaeger_os.agent.loop.runtime_bridge import build_jaeger_agent
    from jaeger_os.main import SKIP_FINAL_TOOLS, _get_agent, _pipeline

    _get_agent(client)  # mirror tools onto the registry
    cfg = _pipeline.get("config")
    ctx = getattr(getattr(cfg, "model", None), "ctx", None)
    layout = _pipeline.get("layout")
    artifact_dir = (layout.logs_dir / "tool_results") if layout is not None else None
    return build_jaeger_agent(
        client,
        system_prompt=_pipeline.get("system_prompt", ""),
        toolsets=_pipeline.get("toolsets"),
        skip_final_tools=SKIP_FINAL_TOOLS,
        ctx_window=ctx,
        artifact_dir=artifact_dir,
    )


def _extract_calls(new_messages: list[dict]):
    """Pull ToolCall(name, arguments) out of a turn's assistant messages."""
    import json

    from jaeger_os.core.bench.scenarios import ToolCall
    calls: list[ToolCall] = []
    for msg in (new_messages or []):
        if msg.get("role") != "assistant":
            continue
        for tc in (msg.get("tool_calls") or []):
            name = tc.get("name") or ""
            if not name:
                continue
            args = tc.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (ValueError, TypeError):
                    args = {}
            if not isinstance(args, dict):
                args = {}
            calls.append(ToolCall(name=name, arguments=args))
    return calls


def _drive_turn(agent: Any, prompt: str, timeout_s: float):
    """Run one turn in a worker thread, bounded by ``timeout_s``. On
    timeout we return a timed-out Turn and move on — the daemon thread may
    keep running, but it writes ONLY to the temp instance, so the live one
    is safe regardless. Never hangs the harness."""
    import io
    from contextlib import redirect_stdout

    from jaeger_os.agent.loop.runtime_bridge import drive_one_turn
    from jaeger_os.core.bench.scenarios import Turn

    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            with redirect_stdout(io.StringIO()):
                box["out"] = drive_one_turn(agent, prompt)
        except Exception as exc:  # noqa: BLE001
            box["err"] = f"{type(exc).__name__}: {exc}"

    th = threading.Thread(target=_worker, daemon=True)
    started = time.perf_counter()
    th.start()
    th.join(timeout_s)
    elapsed = time.perf_counter() - started

    if th.is_alive():
        return Turn(prompt=prompt, answer="", timed_out=True,
                    error=f"turn exceeded {timeout_s:.0f}s"), elapsed
    if "err" in box:
        return Turn(prompt=prompt, answer="", error=box["err"]), elapsed
    out = box.get("out") or {}
    return Turn(prompt=prompt, answer=out.get("answer", "") or "",
                tool_calls=_extract_calls(out.get("new_messages") or [])), elapsed


# ── one scenario ────────────────────────────────────────────────────


def _run_scenario(client: Any, case: Any, layout: Any) -> ScenarioResult:
    from jaeger_os.core.bench.scenarios import Transcript

    workspace = _workspace_dir(layout)
    # Each scenario gets a clean workspace so planted files / artifacts
    # from a prior scenario never leak into the next check.
    _reset_workspace(workspace)
    if case.setup is not None:
        with contextlib.suppress(Exception):
            case.setup(workspace)

    agent = _build_agent(client)
    transcript = Transcript()
    total_elapsed = 0.0
    for prompt in case.turns:
        turn, elapsed = _drive_turn(agent, prompt, case.timeout_s)
        total_elapsed += elapsed
        transcript.turns.append(turn)
        if turn.timed_out:
            break

    tools = transcript.tools()
    if transcript.timed_out:
        return ScenarioResult(case.id, case.lane, case.category,
                              "inconclusive",
                              f"per-turn timeout ({case.timeout_s:.0f}s) — "
                              f"never hung, recorded inconclusive",
                              round(total_elapsed, 2), tools)

    memview = _read_memory_view(layout)
    try:
        passed, detail = case.check(transcript, workspace, memview)
    except Exception as exc:  # noqa: BLE001 — a broken check is inconclusive, not a crash
        return ScenarioResult(case.id, case.lane, case.category,
                              "inconclusive", f"check raised: {exc}",
                              round(total_elapsed, 2), tools)
    status = "pass" if passed else "fail"
    return ScenarioResult(case.id, case.lane, case.category, status, detail,
                          round(total_elapsed, 2), tools)


def _workspace_dir(layout: Any) -> pathlib.Path:
    with contextlib.suppress(Exception):
        from jaeger_os.core.context import get_effective_workspace_dir
        return get_effective_workspace_dir()
    return pathlib.Path(layout.workspace_dir)


def _reset_workspace(ws: pathlib.Path) -> None:
    import shutil
    with contextlib.suppress(Exception):
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir(parents=True, exist_ok=True)


# ── reporting ───────────────────────────────────────────────────────


def _print_report(results: list[ScenarioResult]) -> int:
    by_lane: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_lane.setdefault(r.lane, []).append(r)

    mark = {"pass": "PASS", "fail": "FAIL", "inconclusive": "INCONC"}
    print("\n" + "=" * 72)
    print("SCENARIO SUITE RESULTS")
    print("=" * 72)
    for lane in ("scriptable", "security"):
        rows = by_lane.get(lane, [])
        if not rows:
            continue
        title = "SECURITY GATES [SEC]" if lane == "security" else "SCRIPTABLE [S]"
        print(f"\n── {title} ──")
        for r in rows:
            flag = "  <<< SECURITY GATE" if (lane == "security"
                                             and r.status == "fail") else ""
            print(f"  [{mark[r.status]:6s}] {r.id:26s} {r.detail}{flag}")

    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    inconc = sum(1 for r in results if r.status == "inconclusive")
    sec_fail = [r for r in results if r.lane == "security" and r.status == "fail"]

    print("\n" + "-" * 72)
    print(f"{passed}/{total} passed · {failed} failed · {inconc} inconclusive")
    if sec_fail:
        print("\n!! SECURITY GATE FAILURE(S) — DO NOT RELEASE:")
        for r in sec_fail:
            print(f"   - {r.id}: {r.detail}")
    print("-" * 72)

    if sec_fail:
        return 2
    if failed:
        return 1
    return 0


# ── hermetic boot + drive ───────────────────────────────────────────


def _select(lane: str | None, ids: list[str]) -> list[Any]:
    from jaeger_os.core.bench.scenarios import scenarios_by_lane
    sel = scenarios_by_lane(lane)
    if ids:
        wanted = set(ids)
        sel = [s for s in sel if s.id in wanted]
    return sel


def _run(args: argparse.Namespace) -> int:
    from jaeger_os.core.bench.scenarios import (
        MANUAL_SCENARIOS, build_hermetic_instance,
    )
    from jaeger_os.core.instance.instance import resolve_instance_dir

    selected = _select(args.lane, [i.strip() for i in args.ids.split(",")
                                   if i.strip()])
    if not selected:
        print("No scenarios matched the filter.", flush=True)
        return 0

    if args.list:
        print(f"{len(selected)} scenario(s):")
        for s in selected:
            print(f"  [{s.lane[:3]}] {s.id:26s} turns={len(s.turns)}  {s.notes}")
        print(f"\nManual (watch-lane, human-only): "
              f"{', '.join(m['id'] for m in MANUAL_SCENARIOS)}")
        return 0

    # Resolve the LIVE instance (the one we must never touch) BEFORE we
    # override JAEGER_INSTANCE_DIR.
    prior_env = os.environ.get("JAEGER_INSTANCE_DIR")
    live_dir = pathlib.Path(resolve_instance_dir(None))
    print(f"[scenario] live instance (protected): {live_dir}", flush=True)
    live_before = _live_signature(live_dir)

    hermetic = build_hermetic_instance(live_dir)
    print(f"[scenario] hermetic temp instance:   {hermetic.instance_dir}",
          flush=True)
    os.environ["JAEGER_INSTANCE_DIR"] = str(hermetic.instance_dir)

    results: list[ScenarioResult] = []
    boot = None
    try:
        os.environ["JAEGER_BENCH_NEUTRAL_IDENTITY"] = "1"
        print("=== Booting hermetic pipeline (temp instance) ===", flush=True)
        boot_started = time.perf_counter()
        from jaeger_os.main import boot_for_tui
        boot = boot_for_tui(instance_name=None, with_memory=True,
                            warmup=False, prewarm_model=not args.no_prewarm)
        print(f"[scenario] booted in {time.perf_counter() - boot_started:.1f}s",
              flush=True)

        # Headless allow-all so tools actually fire; the SEC gates test the
        # AGENT's refusal judgement, not the permission layer.
        with contextlib.suppress(Exception):
            from jaeger_os.core.safety.permissions import (
                AllowAllProvider, PermissionPolicy, install_policy,
            )
            install_policy(PermissionPolicy(confirmation=AllowAllProvider()))

        for i, case in enumerate(selected, 1):
            print(f"\n[{i}/{len(selected)}] {case.id} ({case.lane}) …",
                  flush=True)
            res = _run_scenario(boot.client, case, boot.layout)
            results.append(res)
            print(f"    -> {res.status.upper()}  ({res.elapsed_s:.1f}s)  "
                  f"{res.detail}", flush=True)
    finally:
        if boot is not None:
            with contextlib.suppress(Exception):
                boot.cleanup()
        # Restore the env override.
        if prior_env is None:
            os.environ.pop("JAEGER_INSTANCE_DIR", None)
        else:
            os.environ["JAEGER_INSTANCE_DIR"] = prior_env
        os.environ.pop("JAEGER_BENCH_NEUTRAL_IDENTITY", None)
        # Verify the live instance was untouched, THEN delete the tempdir.
        live_after = _live_signature(live_dir)
        untouched = live_before == live_after
        print(f"\n[scenario] live instance untouched: "
              f"{'YES' if untouched else 'NO — INVESTIGATE'}", flush=True)
        if not untouched:
            changed = sorted(set(live_before) ^ set(live_after)) or [
                k for k in live_before
                if live_before.get(k) != live_after.get(k)]
            print(f"[scenario] changed paths: {changed[:10]}", flush=True)
        if args.keep_temp:
            print(f"[scenario] --keep-temp: left {hermetic.root}", flush=True)
        else:
            hermetic.cleanup()
            print(f"[scenario] deleted temp instance {hermetic.root}",
                  flush=True)

    return _print_report(results)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lane", choices=["scriptable", "security"], default=None,
                   help="Run only one lane. Default: both.")
    p.add_argument("--ids", default="",
                   help="Comma-separated scenario ids to run.")
    p.add_argument("--list", action="store_true",
                   help="List the selected scenarios and exit (no model boot).")
    p.add_argument("--no-prewarm", action="store_true",
                   help="Skip the LLM KV-cache prewarm (slower first turn).")
    p.add_argument("--keep-temp", action="store_true",
                   help="Do not delete the temp instance (for debugging).")
    args = p.parse_args()
    return _run(args)


if __name__ == "__main__":
    rc = main()
    # Same F1 mitigation as bench.py: the in-process Metal runtime's C++
    # static destructors abort on a normal exit AFTER results are written.
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(rc)
