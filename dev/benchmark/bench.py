#!/usr/bin/env python3
"""The JROS benchmark — ONE command, one categorized corpus.

This replaces the old flat / sanity / sweep script sprawl. There is a
single corpus (:mod:`jaeger_os.core.bench.cases`, categorized by tag)
and a single runner; the mode is a flag, not a different file:

    python dev/benchmark/bench.py                     # full corpus, active model
    python dev/benchmark/bench.py --quick             # 8-case smoke
    python dev/benchmark/bench.py --category skill     # one category
    python dev/benchmark/bench.py --category kanban,deepthink
    python dev/benchmark/bench.py --models a.gguf,b.gguf   # multi-model sweep

Two entry points share this ONE corpus (see dev/docs/pipelines/):
  • dev (this script) — the real agentic pipeline, offline, in-process.
  • agent-internal (the ``run_benchmark`` tool) — the SAME cases run by
    the agent inside the live app, all nodes + persona up (full system).

Model is LOCKED for a run — the dev bench measures how ONE specific
model performs across every category. Deep-think cases therefore check
that the agent RECOGNIZES the escalation moment (queues a deepthink
task) — they do NOT swap models; the queued task stays unapproved and
the background coder-model worker never fires in a single bench turn.
The real model-flip is exercised by the agent/full-system entry point.

Categories (tags): routing · memory · multistep · recovery · multiturn ·
files · web · code · schedule · safety · skill · kanban · deepthink ·
self_improve · workflow · persona.

Permissions: a benchmark measures CAPABILITY, not the operator's confirm
policy. So the run forces ``permissions.mode = allow`` (backup + restore
around the run) — otherwise a confirm-mode instance denies every
file/schedule/kanban tool headless and the model looks broken when it
routed correctly. Disable with ``--no-force-allow``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Iterator


def _repo_root() -> pathlib.Path:
    """Repo root = the dir holding pyproject.toml (survives file moves)."""
    here = pathlib.Path(__file__).resolve()
    for p in here.parents:
        if (p / "pyproject.toml").is_file():
            return p
    return here.parents[2]


_REPO = _repo_root()
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
os.chdir(_REPO)

_QUICK_LIMIT = 8


# ── permission posture (force allow, restore after) ─────────────────


def _resolve_active_config_path() -> pathlib.Path:
    """The config.yaml the bench subprocess will actually load — the
    ACTIVE instance (JAEGER_INSTANCE_DIR wins for one-off overrides)."""
    from jaeger_ai.core.instance.instance import resolve_instance_dir
    env_dir = os.environ.get("JAEGER_INSTANCE_DIR")
    root = pathlib.Path(env_dir) if env_dir else pathlib.Path(resolve_instance_dir(None))
    return root / "config.yaml"


def _rewrite_config(text: str, *, model_path: str | None,
                    force_allow: bool) -> str:
    """YAML round-trip: optionally set model.model_path (+backend) and
    force permissions.mode=allow. ruamel (comment-preserving) → pyyaml."""
    def _mutate(data: dict) -> None:
        if model_path and isinstance(data.get("model"), dict):
            data["model"]["model_path"] = model_path
            is_gguf = model_path.endswith(".gguf") and not os.path.isdir(model_path)
            data["model"]["backend"] = "llama_cpp_python" if is_gguf else "mlx_lm"
        if force_allow:
            perms = data.get("permissions")
            if not isinstance(perms, dict):
                perms = {}
                data["permissions"] = perms
            perms["mode"] = "allow"

    try:
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.preserve_quotes = True
        data = yaml.load(text)
        if isinstance(data, dict):
            _mutate(data)
            buf = io.StringIO()
            yaml.dump(data, buf)
            return buf.getvalue()
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 — fall through to pyyaml
        pass
    import yaml as _yaml
    data = _yaml.safe_load(text)
    if isinstance(data, dict):
        _mutate(data)
        return _yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    return text


@contextlib.contextmanager
def _prepared_config(*, model_path: str | None,
                     force_allow: bool) -> Iterator[None]:
    """Back up config.yaml, apply model/permission overrides, restore on
    exit (even on crash) so the operator's instance is untouched."""
    if not model_path and not force_allow:
        yield
        return
    path = _resolve_active_config_path()
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text(
            _rewrite_config(original, model_path=model_path,
                            force_allow=force_allow),
            encoding="utf-8")
        yield
    finally:
        try:
            path.write_text(original, encoding="utf-8")
        except OSError:
            pass


def _canonical_model_name(model_path: object) -> str:
    stem = pathlib.Path(str(model_path)).stem
    try:
        from jaeger_ai.core.models.model_resolver import MODEL_REGISTRY
        filename = pathlib.Path(str(model_path)).name.lower()
        for key, info in MODEL_REGISTRY.items():
            if str(info.get("hf_file", "")).lower() == filename:
                return key
    except Exception:  # noqa: BLE001
        pass
    return stem.lower().replace("_", "-")


# ── category rollup ─────────────────────────────────────────────────

# The categories worth breaking out on the console, in report order.
_REPORT_CATEGORIES = (
    "routing", "memory", "multistep", "recovery", "multiturn",
    "files", "web", "code", "schedule", "safety",
    "skill", "kanban", "deepthink", "self_improve", "workflow", "persona",
)


def _category_breakdown(rows: list) -> dict[str, dict[str, int]]:
    """Per-category pass/total from the run's rows (a row counts toward
    every tag it carries — categories overlap by design)."""
    out: dict[str, dict[str, int]] = {}
    for cat in _REPORT_CATEGORIES:
        hits = [r for r in rows if cat in (r.get("tags") or [])]
        if hits:
            out[cat] = {"passed": sum(1 for r in hits if r.get("case_pass")),
                        "total": len(hits)}
    return out


# ── single-model run ────────────────────────────────────────────────


def _run_single(args: argparse.Namespace) -> int:
    """Boot the real pipeline once, run the (filtered) corpus, write
    results + a category breakdown, refresh HISTORY.md."""
    tag_list = [t.strip() for t in (args.category or "").split(",") if t.strip()]
    id_list = [i.strip() for i in (args.ids or "").split(",") if i.strip()]
    cap = _QUICK_LIMIT if args.quick else (args.limit if args.limit > 0 else None)

    print("=== Booting JROS pipeline ===", flush=True)
    # Neutral identity from BOOT so the prewarmed first-turn prefix matches
    # the prompt run_bench's _neutral_identity_guard rebuilds (same flag →
    # identical string). Process-scoped; dies with this CLI run.
    os.environ["JAEGER_BENCH_NEUTRAL_IDENTITY"] = "1"
    boot_started = time.perf_counter()
    with _prepared_config(model_path=None, force_allow=not args.no_force_allow):
        from jaeger_ai.main import boot_for_tui
        boot = boot_for_tui(instance_name=None, with_memory=True,
                            warmup=not args.no_warmup)
        load_s = time.perf_counter() - boot_started
        print(f"[boot] loaded in {load_s:.2f}s", flush=True)

        from jaeger_ai.core.bench import run_bench, summarise

        corpus = None
        if args.corpus == "B":
            from jaeger_ai.core.bench.cases_b import CASES_B
            corpus = CASES_B
            print(f"=== Corpus B ({len(corpus)} cases) ===", flush=True)

        def _on_row(idx, total, case_id, passed, elapsed_s):
            mark = "✓" if passed else "✗"
            print(f"  [ROW {idx:02d}] {case_id:40s} pass={mark}  "
                  f"{elapsed_s:5.2f}s", flush=True)

        started = time.perf_counter()
        try:
            rows = run_bench(boot.client, cases=corpus, tags=tag_list or None,
                             ids=id_list or None, limit=cap, progress=_on_row,
                             hermetic=args.hermetic)
        finally:
            with contextlib.suppress(Exception):
                boot.cleanup()
        wall = time.perf_counter() - started

    summary = summarise(rows)
    summary["wall_s"] = round(wall, 2)
    summary["load_s"] = round(load_s, 2)
    summary["category_breakdown"] = _category_breakdown(summary.get("rows") or [])

    model_name = "unknown"
    try:
        from jaeger_ai.main import _pipeline as _pl
        _mp = getattr(getattr(_pl.get("config"), "model", None), "model_path", None)
        if _mp:
            summary["model_path"] = str(_mp)
            model_name = _canonical_model_name(_mp)
            summary["model_name"] = model_name
    except Exception:  # noqa: BLE001
        pass
    ts = time.strftime("%Y%m%d-%H%M%S")
    summary["run_id"] = ts
    try:
        from jaeger_ai.core.bench.cases import BENCHMARK_VERSION
        summary["benchmark_version"] = BENCHMARK_VERSION
    except Exception:  # noqa: BLE001
        pass

    # Per-run data → results/<model>/<ts>/ (gitignored scratch). The
    # committed leaderboard is HISTORY.md; the aggregator reads results/.
    out_dir = _REPO / "dev/benchmark" / "results" / model_name / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{model_name}-{ts}"
    (out_dir / f"{prefix}-rows.jsonl").write_text(
        "\n".join(json.dumps(r, default=str, ensure_ascii=False)
                  for r in summary["rows"]) + "\n", encoding="utf-8")
    (out_dir / f"{prefix}-summary.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "rows"},
                   indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    # Human-readable per-run digest — the JSON is for the aggregator /
    # machine consumers; this is for eyeballing a run after the fact
    # (overall → per-category → per-prompt, incl. skill selection).
    m = summary.get("metrics") or {}
    log_lines = [
        f"# {model_name} — JROS bench  ({ts})  corpus v{summary.get('benchmark_version','?')}",
        f"# {summary['passed']}/{summary['total']} passed  errors={summary['errors']}  "
        f"wall={wall:.1f}s  load={load_s:.1f}s",
        f"# avg={m.get('avg_latency_s',0):.2f}s p50={m.get('p50_latency_s',0):.2f}s "
        f"p95={m.get('p95_latency_s',0):.2f}s  tok/s={m.get('answer_tokens_per_sec',0):.1f}",
        "",
        "## by category",
    ]
    for cat, cnt in summary["category_breakdown"].items():
        log_lines.append(f"  {cat:14s} {cnt['passed']:2d}/{cnt['total']:<2d}")
    log_lines += ["", "## per prompt"]
    for i, r in enumerate(summary.get("rows") or []):
        mark = "✓" if r.get("case_pass") else "✗"
        extra = ""
        if r.get("skill_ok") is not None:
            sk = "✓" if r.get("skill_ok") else "✗"
            extra = f"  skill={sk} viewed={r.get('skills_viewed') or []}"
        log_lines.append(
            f"  [ROW {i:02d}] {r.get('id','?'):40s} pass={mark}  "
            f"{r.get('elapsed_s',0):5.2f}s  tools={r.get('tools_called') or []}{extra}")
    (out_dir / f"{prefix}.log").write_text("\n".join(log_lines) + "\n",
                                           encoding="utf-8")

    # Full sent/process/expected/outcome transcript, per run, next to the data.
    with contextlib.suppress(Exception):
        import sys as _sys
        _sys.path.insert(0, str(_REPO / "dev/benchmark"))
        from make_transcript import render as _render
        (out_dir / f"{prefix}-transcript.md").write_text(
            _render(out_dir / f"{prefix}-rows.jsonl"), encoding="utf-8")

    total = summary["total"] or 1
    print(f"\n{summary['passed']}/{summary['total']} passed "
          f"({100 * summary['passed'] / total:.0f}%); "
          f"errors={summary['errors']}; wall={wall:.1f}s", flush=True)
    print("── by category ─────────────────────────", flush=True)
    for cat, cnt in summary["category_breakdown"].items():
        print(f"  {cat:14s} {cnt['passed']:2d}/{cnt['total']:<2d}", flush=True)
    print(f"Wrote {out_dir}", flush=True)

    if not os.environ.get("JAEGER_SUPPRESS_HISTORY"):
        with contextlib.suppress(Exception):
            from jaeger_ai.cli.verbs.bench_history_verb import write_history_md
            written = write_history_md()
            if written:
                print(f"Updated {written}", flush=True)
    return 0 if summary["passed"] == summary["total"] else 1


# ── multi-model sweep ───────────────────────────────────────────────


def _run_sweep(args: argparse.Namespace) -> int:
    """Run the SAME corpus across several models, one cold subprocess
    each (isolation — a crash on one model doesn't poison the rest).
    Each subprocess is this very script in single mode."""
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    print(f"=== Sweep: {len(models)} model(s) ===", flush=True)
    config_path = _resolve_active_config_path()
    original = config_path.read_text(encoding="utf-8")
    rc = 0
    try:
        for i, mp in enumerate(models, 1):
            print(f"\n─── [{i}/{len(models)}] {mp} ───", flush=True)
            config_path.write_text(
                _rewrite_config(original, model_path=mp,
                                force_allow=not args.no_force_allow),
                encoding="utf-8")
            child = [sys.executable, str(pathlib.Path(__file__).resolve())]
            if args.corpus != "A":
                child += ["--corpus", args.corpus]
            if args.category:
                child += ["--category", args.category]
            if args.quick:
                child += ["--quick"]
            if args.limit > 0:
                child += ["--limit", str(args.limit)]
            if args.no_warmup:
                child += ["--no-warmup"]
            # The child must NOT re-force perms (config already prepared)
            # and must NOT regenerate HISTORY 15× — do it once at the end.
            child += ["--no-force-allow"]
            env = {**os.environ, "JAEGER_SUPPRESS_HISTORY": "1"}
            result = subprocess.run(child, env=env)
            rc = rc or result.returncode
    finally:
        config_path.write_text(original, encoding="utf-8")
    with contextlib.suppress(Exception):
        from jaeger_ai.cli.verbs.bench_history_verb import write_history_md
        written = write_history_md()
        if written:
            print(f"\nUpdated {written}", flush=True)
    return rc


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--category", "--tags", dest="category", default="",
                   help="Comma-separated categories/tags to run. Empty = "
                        "full corpus. See the module docstring for the list.")
    p.add_argument("--ids", default="", help="Comma-separated case ids.")
    p.add_argument("--corpus", choices=["A", "B"], default="A",
                   help="Which corpus: A = the original cases (default); B = "
                        "the parallel same-category/new-prompt set (cases_b) — "
                        "tests generalization, catches prompt-memorization.")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap number of cases (after filtering). 0 = none.")
    p.add_argument("--quick", action="store_true",
                   help=f"Smoke run — first {_QUICK_LIMIT} cases.")
    p.add_argument("--models", default="",
                   help="Comma-separated model paths → multi-model sweep.")
    p.add_argument("--no-warmup", action="store_true",
                   help="Skip the llama-cpp prewarm pass.")
    p.add_argument("--no-force-allow", action="store_true",
                   help="Don't force permissions.mode=allow for the run.")
    p.add_argument("--hermetic", dest="hermetic", action="store_true",
                   default=True, help="Snapshot+restore mutable memory "
                                      "files around the run (default).")
    p.add_argument("--no-hermetic", dest="hermetic", action="store_false",
                   help="Let bench writes persist (legacy).")
    args = p.parse_args()
    return _run_sweep(args) if args.models else _run_single(args)


if __name__ == "__main__":
    rc = main()
    # F1 mitigation (STATUS.md; upstream llama.cpp PR #17869): the bench
    # always loads the in-process Metal runtime; a normal interpreter exit
    # runs C++ static destructors that abort in ggml_metal_device_free —
    # SIGABRT + a crash report AFTER all results are already written.
    # Everything is flushed/committed by now; skip the doomed destructors.
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(rc)
