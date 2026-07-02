"""``jaeger bench history`` — rolling leaderboard across every bench run.

Each bench run today writes a fresh artifact
(``dev/benchmark/flat/<model>/<ts>/`` for single-model runs,
``dev/benchmark/sweep/RESULTS_<ts>.md`` and ``sweep_rows.jsonl`` for
multi-model sweeps). Nothing aggregates them — "what's the best model
on this machine?" requires walking the directory tree and reading
each file.

This verb fixes that. It scans the bench history, attributes results
to models, and renders a leaderboard sorted by best routing accuracy.
Two output modes:

  jaeger bench history            # print the leaderboard
  jaeger bench history --write    # also write dev/benchmark/HISTORY.md

Data sources (skipped silently when missing):

  * ``dev/benchmark/sweep/sweep_rows.jsonl`` — one row per per-model
    sweep invocation. Older format from before the metrics block
    existed.
  * ``dev/benchmark/flat/<model>/<ts>/summary.json`` — modern per-run
    summaries.  Now stamped with ``model_name`` / ``model_path``
    (added 2026-05-27).  Older summaries land in the "unknown model"
    bucket — call those out with a count so the user can re-run them
    if it matters.

0.3.0 note: the writer-side scripts used to land artifacts under
``benchmark/...`` while this verb read from ``dev/benchmark/...``,
so fresh runs silently dropped off the leaderboard.  The writers
(``dev/benchmark/run_flat_bench.py`` + ``run_model_sweep.py``) were
fixed to match this verb's read path; the comment trail there
remembers the migration.

We do not parse the rendered ``RESULTS_*.md`` files — the JSONL +
JSON sources have everything the markdown does and more.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable


# Benchmark-generation cutoff. The 2026-05-27 pipeline overhaul
# (drift-parser fixes, skip-final removal, the 51-case corpus
# replacing the old 34-case Level-1 suite, real tokenizer TPS)
# made earlier runs non-comparable — a May-24 "67%" and a May-27
# "67%" measure different things. The leaderboard defaults to
# showing ONLY runs on/after this date so the ranking is
# apples-to-apples. ``--all`` (or ``--since`` with an earlier date)
# brings the historical runs back for archaeology.
_DEFAULT_SINCE = "2026-05-29"

# The current corpus generation — MUST track ``cases.BENCHMARK_VERSION``
# (the source of truth; 1.2 = 65 cases). When the corpus is bumped, bump here
# too, or current runs get FILTERED OUT of the leaderboard — the exact bug this
# guards against (the bump to 1.2 left this stuck at 1.1, so every 65-case run
# was excluded). Going-forward runs stamp ``benchmark_version`` explicitly;
# legacy runs infer by case count via ``_version_from_cases``.
_CURRENT_BENCH_VERSION = "1.2"
_BENCH_V11_CUTOFF = "2026-05-29"


def _infer_bench_version(summary: dict[str, Any]) -> str:
    """Return the corpus version for a run.

    Going-forward runs have ``benchmark_version`` stamped explicitly
    by ``run_flat_bench.py`` (from ``cases.BENCHMARK_VERSION``).
    Legacy summaries without that field are inferred from
    ``total`` case count — the definitional difference between
    versions:

      * 1.1 corpus: 59 cases (added T1c hallucination + T3 cross-turn
        + T5 safety tiers).
      * 1.0 corpus: 51 cases (pre-safety-tier).

    Case count beats date as a signal because some 1.0 (51-case)
    runs happened on the v1.1 cutoff date itself (early-morning runs
    before the T5 cases landed in the corpus)."""
    explicit = summary.get("benchmark_version")
    if explicit:
        return str(explicit)
    return _version_from_cases(int(summary.get("total", 0) or 0))


def _version_from_cases(total: int) -> str:
    """Corpus version inferred from case count for legacy runs without an
    explicit ``benchmark_version`` stamp: 65 = v1.2, 59 = v1.1, else v1.0.
    (Tiered so a real 59-case v1.1 run isn't mislabeled as the current 1.2.)"""
    if total >= 65:
        return "1.2"
    if total >= 59:
        return "1.1"
    return "1.0"

# Minimum case count for a run to count toward the leaderboard.
# Debugging mini-benches (``--limit 3/5/10``) trivially hit 100%
# routing and pollute the "best route%" column. The full corpus is
# 51 cases; a threshold of 50 keeps full runs, drops the noise, and
# tolerates a one-off corpus tweak. ``--min-cases 0`` disables the
# filter for partial-run analysis.
_DEFAULT_MIN_CASES = 50


def _canonical_model_name(
    model_path: str | None = None,
    *,
    name: str | None = None,
) -> str:
    """Collapse GGUF path/name casing drift to a single canonical slug.

    The slug is ALWAYS dash-normalised (``q4_k_m`` → ``q4-k-m``), whether
    it came from a registry-key match or the raw name. Registry keys use
    underscores; if we returned them verbatim while raw names got dashed,
    the SAME model would show up twice on the leaderboard under two
    spellings (the duplicate-row bug). Normalising both paths the same
    way keeps one row per model."""
    raw_name = name or ""
    if model_path:
        p = pathlib.Path(str(model_path))
        raw_name = raw_name or p.stem
        filename = p.name.lower()
    else:
        filename = f"{raw_name}.gguf".lower() if raw_name else ""

    try:
        from jaeger_os.core.models.model_resolver import MODEL_REGISTRY
        for key, info in MODEL_REGISTRY.items():
            hf_file = str(info.get("hf_file", ""))
            if filename and hf_file.lower() == filename:
                return key.replace("_", "-")
            if raw_name and pathlib.Path(hf_file).stem.lower() == raw_name.lower():
                return key.replace("_", "-")
    except Exception:  # noqa: BLE001 — history rendering should not fail
        pass

    return raw_name.lower().replace("_", "-") if raw_name else "unknown"


def _cmd_bench_history_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger bench history", add_help=False,
    )
    parser.add_argument(
        "--write", action="store_true",
        help="also write dev/benchmark/HISTORY.md",
    )
    parser.add_argument(
        "--family", default=None,
        help="filter by model family substring (e.g. 'gemma' or 'qwen')",
    )
    parser.add_argument(
        "--top", type=int, default=0,
        help="cap output to top N entries by best routing % (0 = all)",
    )
    parser.add_argument(
        "--since", default=_DEFAULT_SINCE,
        help=f"only include runs on/after this date (YYYY-MM-DD). "
             f"Default {_DEFAULT_SINCE} — the current benchmark "
             f"generation. Older runs used a different corpus/pipeline "
             f"and aren't comparable.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="include every run regardless of date (overrides --since). "
             "Use for archaeology across benchmark generations.",
    )
    parser.add_argument(
        "--min-cases", type=int, default=_DEFAULT_MIN_CASES,
        help=f"only count runs with at least this many cases (default "
             f"{_DEFAULT_MIN_CASES}). Excludes debugging mini-benches "
             f"(--limit 3/5) that trivially hit 100%%. Set 0 to disable.",
    )
    parser.add_argument(
        "--include-unknown", action="store_true",
        help="include runs with no model attribution (the 'unknown' "
             "bucket from before model_name was stamped). Excluded by "
             "default — an unnamed run can't be compared to anything.",
    )
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger bench history [--write] [--family STR] "
            "[--top N] [--since YYYY-MM-DD] [--all]\n"
            "\n"
            "Rolling leaderboard across bench runs on this machine.\n"
            "Reads sweep + flat-bench artifacts and aggregates per model.\n"
            "\n"
            "  --write       also write dev/benchmark/HISTORY.md\n"
            "  --family STR  only show models whose name contains STR\n"
            "  --top N       cap to top-N by routing %\n"
            f"  --since DATE  only runs on/after DATE (default {_DEFAULT_SINCE},\n"
            "                the current benchmark generation)\n"
            "  --all         include every run regardless of date\n",
            file=sys.stderr,
        )
        return 0

    repo = _repo_root()
    since = None if args.all else args.since
    md = render_history_md(
        repo,
        since=since,
        min_cases=args.min_cases,
        include_unknown=args.include_unknown,
        family=args.family,
        top=args.top,
    )
    print(md)

    if args.write:
        out_path = repo / "dev/benchmark" / "HISTORY.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"\nwrote {out_path}", file=sys.stderr)
    return 0


def render_history_md(
    repo: pathlib.Path,
    *,
    since: str | None = _DEFAULT_SINCE,
    min_cases: int = _DEFAULT_MIN_CASES,
    include_unknown: bool = False,
    include_uninstalled: bool = False,
    family: str | None = None,
    top: int = 0,
) -> str:
    """Collect → filter → aggregate → render the leaderboard markdown.
    Pure: no printing, no file writes. The CLI verb and the
    auto-update hook both call this so the filtering logic lives in
    one place.

    ``include_uninstalled``: by default the leaderboard filters out
    entries for models that aren't on disk anymore (deleted from the
    LM Studio cache). The historical data is preserved in
    ``dev/benchmark/flat/`` and ``sweep_rows.jsonl``; set this true to
    include it in the rendered report."""
    entries = list(_collect_entries(repo))
    # ``since=None`` is the CLI's ``--all`` mode: show every run
    # regardless of corpus version (archaeology). Otherwise the active
    # leaderboard ranks only current-version runs — a 1.0 51-case
    # run isn't comparable with a 1.1 59-case run.
    archived_entries: list[dict[str, Any]] = []
    if since is not None:
        archived_entries = [
            e for e in entries
            if e.get("benchmark_version", _CURRENT_BENCH_VERSION)
               != _CURRENT_BENCH_VERSION
        ]
        entries = [
            e for e in entries
            if e.get("benchmark_version", _CURRENT_BENCH_VERSION)
               == _CURRENT_BENCH_VERSION
        ]
    # Drop forced-baseline runs (``on``/``off`` on toggle-capable
    # models). The methodology is: the main corpus benchmark measures
    # IDEAL-STATE behaviour (each model in the mode it would actually
    # be deployed in). Forced on/off variants are research data for
    # the sanity probe — same-model decode-rate comparison on a
    # trivial prompt — not corpus rank entries.
    sanity_for_filter = _load_sanity_records(repo)
    def _entry_is_ideal(e: dict[str, Any]) -> bool:
        rec = sanity_for_filter.get(e["model"]) or {}
        capability = _reasoning_mode(rec) if rec else None
        return _is_ideal_state(
            e.get("thinking_mode", "default"), capability
        )
    entries = [e for e in entries if _entry_is_ideal(e)]
    if since:
        entries = [e for e in entries if _ts_to_date(e["ts"]) >= since]
    if min_cases and min_cases > 0:
        entries = [e for e in entries if e.get("cases", 0) >= min_cases]
    if not include_unknown:
        entries = [e for e in entries if e.get("model") != "unknown"]
    if family:
        needle = family.lower()
        entries = [e for e in entries if needle in e["model"].lower()]
    aggregated = _aggregate_by_model(entries)
    # Same aggregation for archived (pre-1.1) data — used by the
    # renderer to show "what we have from the old corpus" so the user
    # can see which models need re-benching on 1.1 to rejoin the
    # active leaderboard.
    archived_aggregated = (
        _aggregate_by_model(archived_entries) if archived_entries else []
    )
    hidden_orphans: list[str] = []
    if not include_uninstalled:
        installed = _installed_model_stems(repo=repo)
        # Only apply the filter when the installed set OVERLAPS with
        # the bench data — otherwise we're in a test fixture or a
        # fresh repo where the real LM Studio dir isn't relevant, and
        # filtering would wipe the leaderboard.
        if installed and any(r["model"] in installed for r in aggregated):
            kept = []
            for r in aggregated:
                if r["model"] in installed:
                    kept.append(r)
                else:
                    hidden_orphans.append(r["model"])
            aggregated = kept
    if top and top > 0:
        aggregated = aggregated[:top]
    return _render(aggregated, all_entries=entries,
                   total_entries=len(entries), since=since,
                   hidden_orphans=hidden_orphans,
                   archived_rows=archived_aggregated)


def write_history_md(repo: pathlib.Path | None = None) -> pathlib.Path | None:
    """Silently (re)generate ``dev/benchmark/HISTORY.md`` with the default
    current-generation filters. Returns the path written, or ``None``
    if the repo / benchmark dir can't be located. Best-effort — never
    raises, so a bench run can call it as a fire-and-forget finalizer
    without risking the run's exit status.

    This is the auto-update hook: ``run_model_sweep.py`` calls it once
    at the end of a sweep, and ``run_flat_bench.py`` calls it after a
    standalone run, so the leaderboard is always current without a
    manual ``jaeger bench history --write``."""
    try:
        repo = repo or _repo_root()
        out_path = repo / "dev/benchmark" / "HISTORY.md"
        if not out_path.parent.exists():
            return None
        md = render_history_md(repo)
        out_path.write_text(md, encoding="utf-8")
        return out_path
    except Exception:  # noqa: BLE001 — auto-update must never break a bench
        return None


# ── collection ─────────────────────────────────────────────────


def _collect_entries(repo: pathlib.Path) -> Iterable[dict[str, Any]]:
    """Walk both bench artifact directories. Each yielded entry has:

      {model, family, source, ts, pass_rate, route_pct, p50_s,
       p95_s, avg_latency_s, tokens_per_sec, tokens_source, cases,
       run_dir}

    Missing fields default to 0 / None / empty so the renderer's
    defensive ``.get()`` calls don't have to special-case anything.

    Dedup rule: ``sweep_rows.jsonl`` is a per-model log line written by
    ``run_model_sweep.py`` after each model finishes a sweep. It's a
    strict subset of the matching ``dev/benchmark/flat/<model>/<ts>/
    summary.json`` — same scoring numbers, but no ``thinking_mode``
    field and no per-case detail. Without dedup, the same run shows
    up twice in the leaderboard: once bucketed as ``(model, default)``
    (sweep row) and once as ``(model, on/off)`` (flat summary). Skip
    the sweep row whenever a flat summary exists for the same
    (model, day) — the flat summary is authoritative."""
    flat = list(_from_flat_summaries(repo))
    flat_seen = {
        (e["model"], _ts_to_date(e.get("ts", "")))
        for e in flat
    }
    for e in _from_sweep_jsonl(repo):
        if (e["model"], _ts_to_date(e.get("ts", ""))) in flat_seen:
            continue
        yield e
    yield from flat


def _from_sweep_jsonl(repo: pathlib.Path) -> Iterable[dict[str, Any]]:
    """Older format. ``dev/benchmark/sweep/sweep_rows.jsonl`` is one
    JSON-per-line of ``ModelResult`` dataclasses, written by
    ``run_model_sweep.py`` after each model finishes."""
    path = repo / "dev/benchmark" / "sweep" / "sweep_rows.jsonl"
    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cases = int(row.get("cases", 0) or 0)
                if cases <= 0:
                    # Row recorded an error or zero-progress timeout —
                    # skip from the leaderboard but you can still see
                    # it via ``cat sweep_rows.jsonl``.
                    continue
                route_pct = (
                    100 * row.get("route_ok", 0) / cases if cases else 0.0
                )
                # sweep_rows is metadata-only — infer version from
                # case count (same rule the flat-summary path uses).
                bv = _version_from_cases(cases)
                ts = row.get("ts") or ""
                model = _canonical_model_name(name=row.get("name") or "unknown")
                yield {
                    "model": model,
                    "family": _family_of(model),
                    "source": "sweep",
                    "ts": ts,
                    "benchmark_version": bv,
                    "pass_rate": route_pct / 100.0,
                    "route_pct": route_pct,
                    "p50_s": float(row.get("p50_turn_s", 0.0) or 0.0),
                    "p95_s": 0.0,    # not captured in older format
                    "avg_latency_s": (
                        float(row.get("elapsed_s", 0.0) or 0.0) / cases
                        if cases else 0.0
                    ),
                    "tokens_per_sec": 0.0,
                    "tokens_source": "n/a",
                    "cases": cases,
                    "run_dir": "dev/benchmark/sweep/",
                }
    except OSError:
        return


def _from_flat_summaries(repo: pathlib.Path) -> Iterable[dict[str, Any]]:
    """Walk ``dev/benchmark/flat/`` for per-run summaries.

    Two layouts supported because we restructured the tree
    2026-05-27 to nest by model:

      * NEW: ``dev/benchmark/flat/<model>/<ts>/summary.json``
      * OLD: ``dev/benchmark/flat/<ts>/summary.json`` (timestamp-only,
        pre-restructure — these always land in the "unknown" bucket
        since model attribution was added at the same time as
        nesting).

    The walk is depth-1 inspect: any dir directly under ``flat/``
    with a ``summary.json`` is a legacy timestamped run; any dir
    without one is a model-named bucket whose grandchildren are
    timestamped runs.
    """
    flat_root = repo / "dev/benchmark" / "results"
    if not flat_root.exists():
        return
    summary_paths: list[pathlib.Path] = []
    for child in sorted(flat_root.iterdir()):
        if not child.is_dir():
            continue
        # OLD layout (pre-2026-05-27): ``flat/<ts>/summary.json``.
        own_summary = _find_summary_in(child)
        if own_summary is not None:
            summary_paths.append(own_summary)
            continue
        # NEW layout: ``flat/<model>/<ts>/`` — peek one level deeper.
        for run_dir in sorted(child.iterdir()):
            if not run_dir.is_dir():
                continue
            nested = _find_summary_in(run_dir)
            if nested is not None:
                summary_paths.append(nested)
    for summary_path in summary_paths:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_dir = summary_path.parent
        metrics = summary.get("metrics") or {}
        model = _canonical_model_name(
            summary.get("model_path"),
            name=summary.get("model_name") or "unknown",
        )
        route_total = int(summary.get("routing_total", 0) or 0)
        route_passed = int(summary.get("routing_passed", 0) or 0)
        route_pct = (100 * route_passed / route_total) if route_total else 0.0
        # Cloud-style thinking toggle (Phase 2). Older summaries don't
        # carry this field — they ran in the model's default mode,
        # which we tag ``default`` so the aggregator's (model, mode)
        # grouping doesn't collide them with explicit on/off runs.
        # ``auto`` is the modern explicit value (current sweep default)
        # — it stays as ``auto`` so the renderer can show "🧠 auto" as
        # the mode label rather than mislabel it "🧠 on" via the
        # default-bucket fallback path.
        thinking_mode = (summary.get("thinking_mode") or "default").lower()
        yield {
            "model": model,
            "family": _family_of(model),
            "source": "flat",
            "ts": summary.get("run_id") or run_dir.name,
            "thinking_mode": thinking_mode,
            **_category_pass(run_dir),
            "pass_rate": float(summary.get("pass_rate", 0.0) or 0.0),
            "route_pct": route_pct,
            "p50_s": float(metrics.get("p50_latency_s", 0.0) or 0.0),
            "p95_s": float(metrics.get("p95_latency_s", 0.0) or 0.0),
            "wall_s": float(summary.get("wall_s", 0.0) or 0.0),
            "passed": int(summary.get("passed", 0) or 0),
            "total": int(summary.get("total", 0) or 0),
            "peak_load": float(summary.get("peak_load", 0.0) or 0.0),
            "answer_tokens_total": int(
                metrics.get("answer_tokens_total", 0) or 0
            ),
            "benchmark_version": _infer_bench_version(summary),
            "avg_latency_s": float(metrics.get("avg_latency_s", 0.0) or 0.0),
            "tokens_per_sec": float(
                metrics.get("answer_tokens_per_sec", 0.0) or 0.0
            ),
            "tokens_source": metrics.get(
                "answer_tokens_source", "whitespace_estimate",
            ),
            "cases": int(summary.get("total", 0) or 0),
            # Make the run_dir path relative to the repo so it works
            # regardless of layout (legacy ``flat/<ts>/`` vs new
            # ``flat/<model>/<ts>/``).
            "run_dir": str(run_dir.relative_to(repo)) + "/",
        }


# Role-category tag groups. ``Deep-think`` is the hard subset (full
# pass on code|multistep|recovery); ``Real-time`` is the easy routing
# subset; ``Safety`` is a regular weighted tier at 10% of the final
# score (was a hard-gate DQ pre-2026-05-29 but every model failed at
# least one safety case in practice, so the DQ collapsed the
# leaderboard — see _score for the full reasoning).
_DEEP_TAGS = frozenset({"code", "multistep", "recovery"})
_CONTEXT_TAGS = frozenset({"memory", "multiturn"})
_MULTITURN_TAGS = frozenset({"multiturn", "cross_turn"})
_SAFETY_TAGS = frozenset({"safety"})

# Score is just ``passed / total`` — every case worth the same
# 1/total fraction. No tier weighting, no hidden math. The per-tier
# columns (Deep-think / Real-time / Multi-turn / Safety) are
# informational breakdowns of WHICH cases passed, not weighted
# contributors. Pass 50/59 → Score 84.7%, period.


def _category_pass(run_dir: pathlib.Path) -> dict[str, int]:
    """Tally full-pass counts by role-category from the run's per-case
    ``rows.jsonl``. Returns zeros when no rows file is present (e.g. an
    aggregated sweep row, which has no per-case tags). Adds a SAFETY
    bucket — pass count feeds the weighted score (10% weight); the list
    of fail IDs surfaces in the per-model detail block so a reader can
    see which specific safety cases tripped."""
    rf = sorted(run_dir.glob("*rows.jsonl"))
    zero = {"deep_pass": 0, "deep_total": 0,
            "rt_pass": 0, "rt_total": 0,
            "ctx_pass": 0, "ctx_total": 0,
            "mt_pass": 0, "mt_total": 0,
            "safety_pass": 0, "safety_total": 0,
            "safety_fail_ids": []}
    if not rf:
        return zero
    dp = dt = rp = rt = cp = ct = mp = mt = sp = st = 0
    safety_fails: list[str] = []
    try:
        for line in rf[0].read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            tags = set(r.get("tags") or [])
            passed = 1 if r.get("case_pass") else 0
            if tags & _DEEP_TAGS:
                dt += 1; dp += passed
            if "routing" in tags:
                rt += 1; rp += passed
            if tags & _CONTEXT_TAGS:
                ct += 1; cp += passed
            if tags & _MULTITURN_TAGS:
                mt += 1; mp += passed
            if tags & _SAFETY_TAGS:
                st += 1
                if passed:
                    sp += 1
                else:
                    safety_fails.append(r.get("id", "?"))
    except (OSError, json.JSONDecodeError):
        return zero
    return {"deep_pass": dp, "deep_total": dt,
            "rt_pass": rp, "rt_total": rt,
            "ctx_pass": cp, "ctx_total": ct,
            "mt_pass": mp, "mt_total": mt,
            "safety_pass": sp, "safety_total": st,
            "safety_fail_ids": safety_fails}


def _find_summary_in(run_dir: pathlib.Path) -> pathlib.Path | None:
    """Locate the summary file in a run directory.

    Two filename conventions coexist:

      * OLD (pre-2026-05-27 evening): ``summary.json``
      * NEW: ``<model>-<ts>-summary.json`` — same model+ts as the
        parent path, repeated in the filename so an out-of-context
        copy still self-identifies.

    We try the old name first (cheaper — single ``Path.exists()``
    call), then glob for the new shape. Returns None if neither
    exists (incomplete run, malformed dir, etc.)."""
    old = run_dir / "summary.json"
    if old.exists():
        return old
    new_candidates = sorted(run_dir.glob("*-summary.json"))
    if new_candidates:
        # Multiple matches → take the lexicographically last (newest
        # timestamp by suffix) — shouldn't happen in practice but
        # defensive.
        return new_candidates[-1]
    return None


def _family_of(name: str) -> str:
    """Best-effort family attribution from the model filename."""
    low = name.lower()
    if "gemma" in low:
        return "gemma"
    if "qwen" in low:
        return "qwen"
    if "llama" in low:
        return "llama"
    if "mistral" in low or "ministral" in low:
        return "mistral"
    if "phi" in low:
        return "phi"
    return "other"


# ── aggregation ────────────────────────────────────────────────


_CAT_KEYS = ("deep_pass", "deep_total", "rt_pass", "rt_total",
             "ctx_pass", "ctx_total", "mt_pass", "mt_total",
             "safety_pass", "safety_total", "safety_fail_ids")


def _latest_category(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-category counts from the most recent run that actually has
    them. Aggregated sweep rows carry none, so we skip past them to the
    newest flat run with per-case rows."""
    for r in runs:  # newest-first
        if any(r.get(k) for k in _CAT_KEYS):
            return {k: r.get(k, 0 if k != "safety_fail_ids" else [])
                    for k in _CAT_KEYS}
    return {k: 0 if k != "safety_fail_ids" else [] for k in _CAT_KEYS}


def _score(model_row: dict[str, Any]) -> tuple[str, bool]:
    """Score = ``passed / total`` from the latest run. Every case
    counts the same — no tier weighting, no hidden math. The Score
    column literally just says "how many of the 59 cases did this
    model pass?"

    Returns ``(display, False)`` — the second element is kept for
    back-compat with callers that still unpack two values.

    The per-tier columns (Deep-think / Real-time / Multi-turn /
    Safety) are informational — they show WHICH cases the model
    passed, not weighted contributors to the score."""
    passed = model_row.get("latest_passed", 0) or 0
    total = model_row.get("latest_total", 0) or 0
    if not total:
        return "—", False
    return f"{passed / total * 100:.1f}%", False


def _aggregate_by_model(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group entries by model name; for each model report best route%,
    latest p50, last run timestamp, run count. Sorted by best
    route% descending, then by latest p50 ascending (so two equal
    accuracy models rank the faster one first).

    A model with 5 runs at ``77.2 / 67.6 / 90.1 / 88.0 / 80.0`` reports
    best=90.1; the ``latest_*`` columns track whichever run had the
    most recent timestamp."""
    # Group by (model, thinking_mode) so a hybrid model running both
    # think-ON and think-OFF gets ONE row per mode — Claude / GPT-o1
    # style. Older runs lacking the field carry ``default`` and stay
    # one row each.
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        mode = e.get("thinking_mode") or "default"
        # Collapse legacy ``default`` into ``auto`` at the bucket-key
        # level — for hybrid models the two are semantically identical
        # (default = no explicit flag = model decides = auto). Without
        # this, the same model shows up twice on the leaderboard when
        # a pre-fix run stamped ``default`` and a post-fix run stamped
        # ``auto``.
        if mode == "default":
            mode = "auto"
        by_key[(e["model"], mode)].append(e)

    out: list[dict[str, Any]] = []
    for (model, thinking_mode), runs in by_key.items():
        # Sort runs newest-first so ``runs[0]`` is the latest.
        runs.sort(key=lambda r: r["ts"], reverse=True)
        latest = runs[0]
        best_route = max(r["route_pct"] for r in runs)
        best_pass = max(r["pass_rate"] for r in runs)
        out.append({
            "model": model,
            "thinking_mode": thinking_mode,
            "family": latest["family"],
            "best_route_pct": best_route,
            "best_pass_rate": best_pass,
            "latest_p50_s": latest["p50_s"],
            "latest_p95_s": latest["p95_s"],
            "latest_wall_s": latest.get("wall_s", 0.0),
            "latest_passed": latest.get("passed", 0),
            "latest_total": latest.get("total", 0),
            "latest_peak_load": latest.get("peak_load", 0.0),
            "latest_tokens_total": latest.get("answer_tokens_total", 0),
            "latest_tokens_per_sec": latest["tokens_per_sec"],
            "latest_tokens_source": latest["tokens_source"],
            "latest_route_pct": latest["route_pct"],
            "latest_ts": latest["ts"],
            "latest_cases": latest["cases"],
            # Path to the latest run dir (relative to repo) — used by
            # the per-model details renderer to read rows.jsonl for the
            # case-by-case breakdown.
            "latest_run_dir": latest.get("run_dir"),
            # Per-category full-pass from the latest run that HAS per-case
            # rows. Includes deep-think / real-time / context / multi-turn
            # / safety counts + safety_fail_ids (surfaced in detail block).
            **_latest_category(runs),
            "run_count": len(runs),
        })
    # Pre-compute the weighted Score so the renderer is a pure
    # projection. Safety is part of the weighted score (10%); a model
    # with safety failures gets a lower number, not a DQ override.
    for r in out:
        score, _ = _score(r)
        r["score_display"] = score
    # Sort: weighted Score desc, then latest p50 asc as the tiebreaker.
    # No DQ branch — every model gets a numeric score, comparable
    # across the board.
    def _sort_key(r):
        # Parse the "78.4%" display back to a number for ordering;
        # missing/zero falls back to best_route_pct so older runs
        # without per-category data still rank sensibly.
        try:
            score_n = float((r.get("score_display") or "0").rstrip("%"))
        except ValueError:
            score_n = r["best_route_pct"]
        return (-score_n, r["latest_p50_s"])
    out.sort(key=_sort_key)
    return out


# ── rendering ──────────────────────────────────────────────────


def _format_duration(seconds: float) -> str:
    """Render a wall-clock duration as a compact human string.
    Examples: ``42s``, ``3m12s``, ``1h08m``. ``—`` when zero/missing."""
    if not seconds or seconds < 0.5:
        return "—"
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def _is_ideal_state(thinking_mode: str, capability: str | None) -> bool:
    """Was this run done in the model's IDEAL operational state?

    Methodology: each model's headline benchmark should be the run
    that matches how it would actually be deployed — not a forced
    baseline. Forced on/off runs are useful as *comparison* data but
    shouldn't masquerade as the model's representative score.

    Ideal state by capability:
      * ``auto`` (toggle-capable, default deploy) — ideal = run let
        the model decide (``auto`` or legacy ``default``)
      * ``manual`` (toggle-capable, user-decide deploy) — ideal =
        ``manual`` runs
      * ``always`` (no off switch) — ideal = any run (no choice)
      * ``never`` (no reasoning) — ideal = any run (no choice)

    A forced ``on`` or ``off`` run on a toggle-capable model is NOT
    its ideal state; it's a research/baseline variant."""
    if capability in ("always", "never"):
        return True   # no choice → every run is ideal-by-default
    if capability == "auto":
        return thinking_mode in ("auto", "default")
    if capability == "manual":
        return thinking_mode == "manual"
    # Unknown capability (no sanity record yet) — assume ideal so we
    # don't decorate every row in the leaderboard as a baseline.
    return thinking_mode in ("auto", "default", "manual")


def _mode_label(thinking_mode: str, capability: str | None = None) -> str:
    """Human label for the leaderboard's Mode column.

    Joins two facts:
      * **capability** — what reasoning options the MODEL supports
        (``auto``/``manual``/``always``/``never``), from the sanity
        record via ``_reasoning_mode``.
      * **thinking_mode** — what was configured for THIS specific run
        (``on``/``off``/``auto``/``manual``/``default``), from the
        run's summary.

    For ``always`` and ``never`` capabilities the run-time mode is
    meaningless (there's no choice) so we surface the capability
    directly — saves the reader from misreading "🧠 on" on a Hermes
    model as a deliberate config decision when actually that model
    can't NOT be off.

    For ``auto``/``manual`` capabilities (toggle-capable models) we
    surface the per-run mode. Legacy ``default`` thinking_mode for
    a toggle-capable model is rendered as the capability label
    (``🧠 auto`` or ``🧠 manual``) — those runs predate the explicit
    toggle but ran in the model's natural decide-per-turn behaviour,
    which IS the ideal state for an ``auto`` deployment.

    Capability is optional so the helper still works in older call
    sites or tests that don't have a sanity record on hand."""
    if capability == "always":
        return "🧠 always"
    if capability == "never":
        return "never"
    if capability == "auto":
        # Auto-capable model: ``default`` (legacy, no explicit flag)
        # AND ``auto`` both mean "model decides" — the ideal state.
        if thinking_mode in ("default", "auto"):
            return "🧠 auto"
        if thinking_mode == "on":
            return "🧠 on"
        if thinking_mode == "off":
            return "off"
        if thinking_mode == "manual":
            return "🧠 manual"
    if capability == "manual":
        if thinking_mode in ("default", "manual"):
            return "🧠 manual"
        if thinking_mode == "on":
            return "🧠 on"
        if thinking_mode == "off":
            return "off"
        if thinking_mode == "auto":
            return "🧠 auto"
    # Unknown capability (no sanity record) — best-effort literal map.
    if thinking_mode in ("on", "default"):
        return "🧠 on"
    if thinking_mode == "off":
        return "off"
    if thinking_mode == "auto":
        return "🧠 auto"
    if thinking_mode == "manual":
        return "🧠 manual"
    return thinking_mode or "—"


def _compact_ts(ts: str) -> str:
    """Normalise to YYYY-MM-DD HH:MM. Handles both ISO
    (``2026-05-24T17:27:00``) and bench-stamp
    (``20260527-122229``) shapes."""
    if not ts:
        return "—"
    if "T" in ts and len(ts) >= 16:
        return ts[:10] + " " + ts[11:16]
    if len(ts) == 15 and ts[8] == "-":
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}"
    return ts


def _installed_model_stems(repo: pathlib.Path | None = None) -> set[str]:
    """Return the set of model file stems currently present on disk.

    Scans all the places a Jaeger user typically keeps GGUFs:

      * ``~/.lmstudio/models/``  — LM Studio's cache (most users)
      * ``~/.jaeger/models/``    — Jaeger's own models dir, populated
        by the wizard's download flow
      * ``<repo>/models/``       — the repo's models folder, which
        usually holds symlinks back to one of the above
      * any path in ``JAEGER_MODEL_DIRS`` (colon-separated env var)

    Symlinks are followed so a repo-level symlink to a file in
    ``~/.lmstudio/models/`` counts as present even if the LM Studio
    dir itself isn't scanned. Returns just the ``.gguf`` stems
    (filename minus extension), skipping ``mmproj-*`` projector files
    — those are multimodal sidecars, not chat models.

    Used by ``render_history_md`` to filter out entries for models
    the user has deleted: keeps the leaderboard reflective of "what
    can I actually run right now" rather than "every model I've ever
    benched on this machine"."""
    roots: list[pathlib.Path] = []
    home = pathlib.Path.home()
    # 0.2.6: model cache moved into <install_root>/.jaeger_os/models/.
    # Resolve lazily so this module stays import-cheap.
    try:
        from jaeger_os.core.instance.instance import operator_state_root
        candidates = (home / ".lmstudio" / "models",
                      operator_state_root() / "models")
    except ImportError:
        candidates = (home / ".lmstudio" / "models",)
    for candidate in candidates:
        if candidate.exists():
            roots.append(candidate)
    if repo is not None:
        repo_models = repo / "models"
        if repo_models.exists():
            roots.append(repo_models)
    for path in os.environ.get("JAEGER_MODEL_DIRS", "").split(":"):
        if path and pathlib.Path(path).exists():
            roots.append(pathlib.Path(path))
    stems: set[str] = set()
    seen_real: set[str] = set()
    for root in roots:
        for gguf in root.rglob("*.gguf"):
            # Dedup by resolved real path — a symlink in the repo's
            # ``models/`` folder pointing at the LM Studio cache
            # shouldn't double-count.
            try:
                real = str(gguf.resolve())
            except OSError:
                real = str(gguf)
            if real in seen_real:
                continue
            seen_real.add(real)
            stem = _canonical_model_name(str(gguf), name=gguf.stem)
            if stem.startswith("mmproj-"):
                continue
            stems.add(stem)
    return stems


def _ts_to_date(ts: str) -> str:
    """Extract a sortable ``YYYY-MM-DD`` from either timestamp shape.
    ISO ``2026-05-24T17:27:00`` → ``2026-05-24``; bench-stamp
    ``20260527-122229`` → ``2026-05-27``. Returns ``""`` for an
    unrecognised shape so it sorts BEFORE any real date (i.e. an
    undated run is treated as ancient and filtered out by --since)."""
    if not ts:
        return ""
    if "T" in ts and len(ts) >= 10:
        return ts[:10]
    if len(ts) >= 8 and ts[:8].isdigit():
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
    return ""


def _load_sanity_records(repo: pathlib.Path) -> dict[str, dict[str, Any]]:
    """Read the most recent sanity-sweep JSONL and return
    ``{model_stem: full_record}``. Full record carries size, load_s,
    gpu_layers, metal/cpu buffer split, hybrid flag, and per-mode raw
    tps. This is the source for both the leaderboard's ``Raw tok/s``
    column and the standalone Hardware-health table — pulling once and
    sharing avoids re-reading the same JSONL twice per render."""
    sanity_dir = repo / "dev/benchmark" / "sanity"
    if not sanity_dir.exists():
        return {}
    jsonl_files = sorted(sanity_dir.glob("SANITY_*.jsonl"))
    if not jsonl_files:
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        for line in jsonl_files[-1].read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("model"):
                continue
            out[r["model"]] = r
    except (OSError, json.JSONDecodeError):
        return {}
    return out


def _load_sanity_raw_tps(repo: pathlib.Path) -> dict[str, float]:
    """Read the most recent sanity-sweep JSONL and return
    ``{model_stem: raw_tps}`` where ``raw_tps`` is the best (max
    across modes) raw decode rate the sanity probe measured.

    ``raw tps`` is the model's per-token GPU rate on a trivial prompt
    — different from the corpus benchmark's ``tps`` (which folds in
    prefill cost, multi-turn turns, and reasoning-token waste). Both
    matter; the bench number measures task efficiency, this measures
    the model's actual decode speed."""
    sanity_dir = repo / "dev/benchmark" / "sanity"
    if not sanity_dir.exists():
        return {}
    jsonl_files = sorted(sanity_dir.glob("SANITY_*.jsonl"))
    if not jsonl_files:
        return {}
    out: dict[str, float] = {}
    try:
        for line in jsonl_files[-1].read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("error"):
                continue
            runs = r.get("runs") or []
            if not runs:
                continue
            best = max((run.get("tps", 0.0) for run in runs), default=0.0)
            if best > 0:
                out[r["model"]] = best
    except (OSError, json.JSONDecodeError):
        return {}
    return out


# Substrings in a model's stem that flag an "always-on" reasoning
# variant — the model reasons every turn, no toggle to disable it.
# Distinguished from "never-reasons" (plain chat model) and from
# "toggle" (chat-template-supported on/off switch).
_ALWAYS_REASONING_TOKENS = ("-r1-", "_r1_", "-r1.", "/r1",
                            "r-zero", "rzero",
                            "reasoning", "qwq")


def _reasoning_mode(rec: dict[str, Any]) -> str:
    """Four-way classification of how reasoning works on this model:

      * ``auto``   — chat template supports thinking on/off AND the
        wizard's default deployment lets the model decide per turn
        (current default for any toggle-capable model)
      * ``manual`` — chat template supports thinking on/off AND it's
        deployed as user-opt-in per turn (alternative for toggle
        models; surfaces here if/when the wizard config flips a model
        to manual)
      * ``always`` — model always reasons, no off switch (DeepSeek-R1,
        ``*-Reasoning-*`` fine-tunes, QwQ — name-detected lineage)
      * ``never``  — model has no reasoning capability at all — plain
        chat model (Hermes, gpt-oss, Mistral-Nemo, gemma-3)

    The sanity probe only knows the capability (toggle vs always vs
    never); ``auto`` vs ``manual`` is a deployment choice. We default
    toggle-capable models to ``auto`` here because that's what the
    wizard configures."""
    if rec.get("hybrid_thinking"):
        # If the record explicitly carries a deployment hint, honour
        # it; otherwise default to "auto" (the wizard's pick).
        deploy = (rec.get("deploy_mode") or "auto").lower()
        return "manual" if deploy == "manual" else "auto"
    name = (rec.get("model") or "").lower()
    if any(tok in name for tok in _ALWAYS_REASONING_TOKENS):
        return "always"
    return "never"


def _render_sanity_table(
    leaderboard_rows: list[dict[str, Any]],
    sanity: dict[str, dict[str, Any]],
) -> str:
    """Per-model hardware-health table from the sanity probe.

    Different question from the corpus leaderboard: did the model fit
    on the GPU, how fast can it decode at the ceiling, does the
    hybrid-thinking toggle work? Sorted in the same order as the
    leaderboard so a reader scrolling down can cross-reference scores
    to hardware health row-for-row.

    Returns ``""`` when no sanity data exists yet (clean repo / never
    ran ``run_model_sanity``) — keeps the report from showing an empty
    table headed by a section title with nothing under it."""
    if not sanity:
        return ""

    # Walk the leaderboard in display order, picking up sanity by model
    # stem. Models in sanity but NOT in the leaderboard are appended
    # afterwards so the section still surfaces hardware data for things
    # that haven't been corpus-benched yet.
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for r in leaderboard_rows:
        rec = sanity.get(r["model"])
        if rec is not None and r["model"] not in seen:
            ordered.append(rec)
            seen.add(r["model"])
    for model_name, rec in sorted(sanity.items()):
        if model_name not in seen:
            ordered.append(rec)
            seen.add(model_name)

    lines = [
        "## Hardware health (sanity probe)",
        "",
        "Did each model fit on the GPU + what's its **ceiling decode "
        "rate** (raw tok/s on a trivial single-prompt — no agent loop, "
        "no tools, no multi-turn)? Different question from the "
        "leaderboard above: that's *task* throughput, this is *decode* "
        "throughput. The gap between them = prefill + tool dispatch + "
        "multi-turn overhead. ``GPU layers`` = how many model layers "
        "got Metal-offloaded (``33/33`` = full); a partial offload "
        "means part of the model is running on CPU and you'll see it "
        "in the Bench tok/s column above. ``VRAM`` / ``CPU buf`` = "
        "buffer sizes after load (CPU buf > 1 GB often means KV cache "
        "spilled). ``Reasoning mode`` is one of four:",
        "",
        "  * ``auto`` — chat template supports thinking on/off, "
        "deployed so the **model** decides per turn (default for "
        "toggle-capable models — gemma-4, Qwen3.x).",
        "  * ``manual`` — same toggle capability, deployed so the "
        "**user** opts in per turn.",
        "  * ``always`` — model always reasons, no off switch "
        "(DeepSeek-R1, ``*-Reasoning`` fine-tunes, QwQ).",
        "  * ``never`` — plain chat model, no reasoning capability "
        "(Hermes, gpt-oss, Mistral-Nemo, gemma-3).",
        "",
        "For ``auto``/``manual`` models both raw rates are shown so "
        "you can see whether the toggle changes anything on a clean "
        "prompt. ``always``/``never`` models have a single rate in "
        "the ``Raw tps (off)`` column. The leaderboard above uses the "
        "same vocabulary in the Mode column to describe how that "
        "specific run was configured (``on`` = forced on for this "
        "run, ``off`` = forced off, ``auto`` = model decided, "
        "``manual`` = user opted in).",
        "",
        "| Model | Size GB | Load | GPU layers | VRAM | CPU buf | "
        "Reasoning mode | Raw tps (on) | Raw tps (off) |",
        "|---|---:|---:|:---:|---:|---:|:---:|---:|---:|",
    ]
    for rec in ordered:
        if rec.get("error"):
            lines.append(
                f"| `{rec['model']}` | — | — | — | — | — | — | — | — |"
            )
            continue
        size = rec.get("size_gb") or 0.0
        load_s = rec.get("load_s") or 0.0
        gpu = rec.get("gpu_layers") or "—"
        full = rec.get("full_offload")
        gpu_disp = f"{gpu} ✅" if full else (f"{gpu} ⚠️" if gpu != "—" else "—")
        vram_mb = rec.get("metal_mb") or 0
        cpu_mb = rec.get("cpu_mb") or 0
        vram = f"{vram_mb / 1024:.1f} GB" if vram_mb else "—"
        # CPU buffer < 100 MB is just scratch — only flag when meaningful.
        cpu = f"{cpu_mb / 1024:.1f} GB" if cpu_mb >= 1024 else (
            f"{cpu_mb} MB" if cpu_mb >= 100 else "—"
        )
        reasoning_disp = _reasoning_mode(rec)
        runs = {run.get("mode"): run for run in (rec.get("runs") or [])}
        # Sanity probe mode labels: ``think`` / ``direct`` for models
        # with reasoning mode, ``default`` for models without (single
        # run — no toggle exists). For no-reasoning-mode models, the
        # single value goes in the "thinking disabled" column (semantic
        # equivalent: no thinking is happening either way) and the
        # "thinking enabled" column shows ``—``.
        think_tps = runs.get("think", {}).get("tps")
        direct_tps = (runs.get("direct")
                      or runs.get("default") or {}).get("tps")
        think_disp = f"{think_tps:.1f}" if think_tps else "—"
        direct_disp = f"{direct_tps:.1f}" if direct_tps else "—"
        lines.append(
            f"| `{rec['model']}` | {size:.1f} | {load_s:.1f}s | "
            f"{gpu_disp} | {vram} | {cpu} | {reasoning_disp} | "
            f"{think_disp} | {direct_disp} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_per_case_block(model_row: dict[str, Any]) -> str:
    """Per-case breakdown for one (model, mode) — every test, the
    pass/fail mark, elapsed seconds, tools dispatched, and the error
    if any. Wrapped in a ``<details>`` block so GitHub / VS Code render
    it collapsed by default; click to expand. Returns ``""`` when the
    model's latest run has no per-case rows on disk (sweep-aggregated
    entries with no flat dir)."""
    rundir_rel = model_row.get("latest_run_dir")
    if not rundir_rel:
        return ""
    rundir = pathlib.Path(rundir_rel)
    if not rundir.is_absolute():
        rundir = (pathlib.Path(__file__).resolve().parents[3]
                  / rundir).resolve()
    rows_paths = sorted(rundir.glob("*rows.jsonl"))
    if not rows_paths:
        return ""
    try:
        raw = rows_paths[0].read_text(encoding="utf-8").splitlines()
        cases = [json.loads(ln) for ln in raw if ln.strip()]
    except (OSError, json.JSONDecodeError):
        return ""
    if not cases:
        return ""

    passed = sum(1 for c in cases if c.get("case_pass"))
    total = len(cases)
    ts = _compact_ts(model_row.get("latest_ts", ""))
    mode = model_row.get("thinking_mode", "default")
    # The per-case block uses the same capability-aware label as the
    # leaderboard so an "always" model doesn't appear as "🧠 on" in its
    # collapsible header. Pulled lazily from the latest sanity sweep.
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    sanity_rec = _load_sanity_records(repo_root).get(model_row["model"])
    capability = _reasoning_mode(sanity_rec) if sanity_rec else None
    mode_label = _mode_label(mode, capability)
    summary = (f"<b>{model_row['model']}</b> &nbsp;·&nbsp; "
               f"<code>{mode_label}</code> &nbsp;·&nbsp; "
               f"<b>{passed}/{total}</b> &nbsp;·&nbsp; latest {ts}")

    table = ["| # | Test | Tags | Pass | Time | Tools called | Error |",
             "|---:|---|---|:--:|---:|---|---|"]
    for i, c in enumerate(cases, start=1):
        ok = "✅" if c.get("case_pass") else "❌"
        elapsed = c.get("elapsed_s") or 0
        tags = ",".join((c.get("tags") or [])[:3])
        # Tools list, truncated so a chatty multi-step row doesn't blow
        # the column. Show count when truncated so the reader still
        # knows it dispatched several.
        tools = c.get("tools_called") or []
        if len(tools) <= 3:
            tools_disp = ",".join(tools) or "—"
        else:
            tools_disp = f"{','.join(tools[:3])}… (+{len(tools)-3})"
        err = c.get("error") or ""
        if err:
            err = err.split(":")[0]  # short error class, not full repr
            if len(err) > 30:
                err = err[:30] + "…"
        # Test id can be long; truncate for the column.
        case_id = c.get("id", "?")
        if len(case_id) > 28:
            case_id = case_id[:27] + "…"
        table.append(
            f"| {i} | `{case_id}` | {tags} | {ok} | "
            f"{elapsed:.1f}s | {tools_disp} | {err or '—'} |"
        )

    return (
        f"<details>\n<summary>{summary}</summary>\n\n"
        + "\n".join(table)
        + "\n\n</details>\n"
    )


def _render(
    rows: list[dict[str, Any]],
    *,
    all_entries: list[dict[str, Any]],
    total_entries: int,
    since: str | None = None,
    hidden_orphans: list[str] | None = None,
    archived_rows: list[dict[str, Any]] | None = None,
) -> str:
    """Three-section report: per-model summary, all-time top runs,
    and the full chronological run log. Together they answer
    "how does each model compare today?" (summary), "what's the
    best we've ever recorded?" (top), and "what was today vs.
    yesterday vs. last week?" (chronological)."""
    if not rows:
        return (
            "# Jaeger-OS bench history\n\n"
            "No bench artifacts found. Run ``jaeger bench run`` or\n"
            "``jaeger bench compare`` first.\n"
        )
    now_iso = datetime.now().isoformat(timespec="seconds")
    window = (
        f"runs on/after **{since}** (current benchmark generation)"
        if since else "ALL runs (every benchmark generation)"
    )
    orphan_note = ""
    if hidden_orphans:
        orphan_note = (
            f" Filtered out **{len(hidden_orphans)}** entr"
            f"{'y' if len(hidden_orphans) == 1 else 'ies'} for "
            "models no longer on disk — historical data preserved in "
            "``dev/benchmark/flat/``."
        )
    lines = [
        "# Jaeger-OS bench history",
        "",
        f"_Generated {now_iso} from {total_entries} run(s) across "
        f"`dev/benchmark/sweep/` and `dev/benchmark/flat/` — showing "
        f"{window}.{orphan_note}_",
        "",
        f"**Bench corpus version: {_CURRENT_BENCH_VERSION}** (cutoff "
        f"{_BENCH_V11_CUTOFF}). The leaderboard ranks only runs of "
        f"this version so the comparison stays apples-to-apples; "
        f"older 1.0 (51-case) runs are archived and shown separately "
        f"at the bottom of the report.",
        "",
        "## Per-model leaderboard",
        "",]
    if hidden_orphans:
        lines += [
            f"<details><summary>"
            f"<i>{len(hidden_orphans)} hidden uninstalled model"
            f"{'' if len(hidden_orphans) == 1 else 's'}</i></summary>",
            "",
            "These models have bench history but their ``.gguf`` files "
            "are no longer in ``~/.lmstudio/models``. Run "
            "``jaeger bench history --write --include-uninstalled`` "
            "to surface them again.",
            "",
            *[f"- `{m}`" for m in sorted(hidden_orphans)],
            "",
            "</details>",
            "",
        ]
    lines += [
        "``Score`` is dead simple: **``passed / total``** from the "
        "latest run. Every case worth the same 1/total — pass 50/59 "
        "→ 84.7%, no tier weighting, no hidden math. The per-tier "
        "columns are informational breakdowns of WHICH cases "
        "passed: ``Deep-think`` = code / multistep / recovery (what "
        "a coding agent needs); ``Real-time`` = routing (what a "
        "fast agent needs); ``Multi-turn`` = multiturn / cross-turn "
        "(stateful conversations); ``Safety`` = refusal / no-"
        "hallucination cases. Latest-run figures, sorted by Score.",
        "",
        "**Methodology — ideal state vs baseline.** Each model is "
        "primarily benched in its **ideal operational state**: "
        "toggle-capable models run with thinking on ``auto`` (the "
        "model decides per turn — what a real user gets); "
        "``always``-reasoning models run as-is (no choice); ``never``-"
        "reasoning models run as-is. Rows tagged ``(baseline)`` are "
        "the **comparison variants** — same model, forced into a "
        "non-ideal state (e.g. an ``auto`` model forced to ``off`` "
        "for direct-mode benchmarking). Use ideal-state rows for "
        "real-world rank, baseline rows for understanding *why* the "
        "ideal works.",
        "",
        "| # | Model | Mode | Family | **Score** | Deep-think | "
        "Real-time | Multi-turn | Safety | Best route% | Latest elapsed | "
        "Tokens/task | Peak TPS | VRAM | Peak load | Latest run | Runs |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    # ``Raw tok/s`` = the model's per-token GPU decode rate measured by
    # ``run_model_sanity`` on a trivial prompt. ``Bench tok/s`` =
    # ``answer_tokens / total_wall_time`` over the corpus (folds in
    # prefill + multi-turn + reasoning-token waste). Both matter:
    # raw = ceiling on speed; bench = how fast a real agent turn feels.
    # The full sanity records also feed the Hardware-health table below
    # — load once, share both.
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    sanity_records = _load_sanity_records(repo_root)
    for i, r in enumerate(rows, start=1):
        latest_ts = _compact_ts(r["latest_ts"])
        dt, rt = r.get("deep_total", 0), r.get("rt_total", 0)
        mt_t = r.get("mt_total", 0)
        st = r.get("safety_total", 0)
        deep = f"{r.get('deep_pass', 0)}/{dt}" if dt else "—"
        real = f"{r.get('rt_pass', 0)}/{rt}" if rt else "—"
        multi = f"{r.get('mt_pass', 0)}/{mt_t}" if mt_t else "—"
        safety = f"{r.get('safety_pass', 0)}/{st}" if st else "—"
        score = r.get("score_display", "—")
        rec = sanity_records.get(r["model"]) or {}
        capability = _reasoning_mode(rec) if rec else None
        thinking_mode = r.get("thinking_mode", "default")
        mode_label = _mode_label(thinking_mode, capability)
        # NOTE: non-ideal rows are filtered out upstream in
        # ``render_history_md``, so every row here represents the
        # model's IDEAL-state run. Forced on/off variants live in the
        # sanity-probe section instead — different question, different
        # data set.
        # VRAM = Metal buffer size from the sanity probe — answers
        # "how big a chunk of GPU memory does this model claim?". Shown
        # in GB for at-a-glance comparison.
        vram_mb = rec.get("metal_mb") or 0
        vram_disp = f"{vram_mb / 1024:.1f} GB" if vram_mb else "—"
        # Peak load = max ``os.getloadavg()`` 1-min average sampled by
        # the bench runner during the run (instrumented per-run). Tells
        # you how hard the model strained the system. Backfilled to
        # "—" for runs that pre-date the instrumentation.
        peak_load = r.get("latest_peak_load")
        load_disp = f"{peak_load:.1f}" if peak_load else "—"
        # Tokens/task = total tokens generated ÷ cases. Captures
        # verbosity: a Thinking model that emits hundreds of reasoning
        # tokens per case (even hidden ones) has a high value; a terse
        # model that answers in 30 tokens has a low value. Different
        # signal from wall time — two models can take similar time but
        # one is generating 10x more tokens to do it.
        tokens_total = r.get("latest_tokens_total", 0) or 0
        total_cases = r.get("latest_total", 0) or 0
        per_task = (tokens_total / total_cases) if total_cases else 0
        tokens_disp = f"{per_task:.0f}" if per_task else "—"
        # Peak TPS = the model's ceiling decode rate on THIS machine
        # (measured by the sanity probe on a trivial single-prompt —
        # no agent loop, no tools, no multi-turn). Model-on-machine
        # metric: same model on different hardware gives a different
        # number; same hardware with different models gives different
        # numbers because architecture / quant / MoE-vs-dense all
        # affect it. The leaderboard's Latest elapsed reflects effective
        # throughput (peak TPS × concision × prefill cost); a high
        # Peak TPS with low Tokens/task is the speed-and-efficiency win.
        rec_runs = rec.get("runs") or []
        peak_tps = max(
            (rn.get("tps", 0.0) for rn in rec_runs), default=0.0
        ) or None
        peak_tps_disp = f"{peak_tps:.1f}" if peak_tps else "—"
        lines.append(
            f"| {i} | `{r['model']}` | {mode_label} | {r['family']} | "
            f"**{score}** | {deep} | {real} | {multi} | {safety} | "
            f"{r['best_route_pct']:.1f}% | "
            f"{_format_duration(r.get('latest_wall_s', 0.0))} | "
            f"{tokens_disp} | {peak_tps_disp} | {vram_disp} | {load_disp} | "
            f"{latest_ts} | {r['run_count']} |"
        )

    # ── hardware health (sanity probe) ────────────────────────
    # Per-model GPU fit + ceiling decode rate from the sanity sweep.
    # Sits between the leaderboard and the per-case details so a reader
    # can answer "is this model healthy on my hardware?" before drilling
    # into specific test failures. Empty when no sanity data exists.
    sanity_section = _render_sanity_table(rows, sanity_records)
    if sanity_section:
        lines += ["", sanity_section]

    # ── per-model latest-run details ──────────────────────────
    # Full per-case breakdown for each (model, mode) — every test,
    # pass/fail, elapsed, tools dispatched, error if any. Collapsed
    # under <details> so the leaderboard stays scannable; expand the
    # block for the model you want to drill into. This is the "I want
    # the full picture for THIS model" view that aggregate scores hide.
    detail_blocks = []
    for r in rows:
        block = _render_per_case_block(r)
        if block:
            detail_blocks.append(block)
    if detail_blocks:
        lines += [
            "",
            "## Per-model run details (latest)",
            "",
            "Each model's most recent run, case-by-case. Click to expand.",
            "Useful for spotting *which* tests a model fails on (a 24/25 "
            "routing model that fails the same case across runs has a "
            "real gap, not noise), and for reading per-case latency to "
            "decide if a high p95 is one outlier or a pattern.",
            "",
        ]
        lines.extend(detail_blocks)

    # ── all-time top runs (top 10 by route%) ──────────────────
    top_runs = sorted(
        [e for e in all_entries if e["cases"] > 0],
        key=lambda e: (-e["route_pct"], e["p50_s"]),
    )[:10]
    if top_runs:
        lines += [
            "",
            "## Top 10 all-time best runs",
            "",
            "Sorted by routing % (then p50 asc). A single great run "
            "doesn't make a model great, but tracking peaks tells "
            "you what's achievable on this hardware.",
            "",
            "| # | Date | Model | Route% | p50 s | p95 s | TPS | Cases | Source |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for i, e in enumerate(top_runs, start=1):
            lines.append(
                f"| {i} | {_compact_ts(e['ts'])} | `{e['model']}` | "
                f"{e['route_pct']:.1f}% | {e['p50_s']:.2f} | "
                f"{e['p95_s']:.2f} | {e['tokens_per_sec']:.1f} | "
                f"{e['cases']} | {e['source']} |"
            )

    # ── full chronological log ───────────────────────────────
    chronological = sorted(
        all_entries, key=lambda e: e["ts"], reverse=True,
    )
    if chronological:
        # Track per-model peak so we can flag whether each row is at
        # or below the model's best — the "are we at peak?" signal.
        peak_by_model: dict[str, float] = {}
        for e in sorted(chronological, key=lambda x: x["ts"]):
            peak_by_model[e["model"]] = max(
                peak_by_model.get(e["model"], 0.0), e["route_pct"],
            )
        lines += [
            "",
            "## Full chronological log",
            "",
            f"Every run we have data for ({len(chronological)} total), "
            "newest first. ``vs peak`` shows the route% delta from "
            "this model's all-time best (0.0% = this run IS the peak).",
            "",
            "| Date | Model | Route% | p50 s | TPS | Cases | vs peak | Source |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for e in chronological:
            peak = peak_by_model.get(e["model"], e["route_pct"])
            delta = e["route_pct"] - peak
            if delta == 0.0:
                vs_peak = "**peak**"
            else:
                vs_peak = f"{delta:+.1f}pp"
            lines.append(
                f"| {_compact_ts(e['ts'])} | `{e['model']}` | "
                f"{e['route_pct']:.1f}% | {e['p50_s']:.2f} | "
                f"{e['tokens_per_sec']:.1f} | {e['cases']} | "
                f"{vs_peak} | {e['source']} |"
            )
    # Footer: token-source caveat.
    estimate_count = sum(
        1 for r in rows
        if r["latest_tokens_source"] == "whitespace_estimate"
    )
    if estimate_count:
        lines.append("")
        lines.append(
            f"_{estimate_count} model(s) report **whitespace-estimate** "
            f"tokens/sec — the adapter didn't surface a ``usage`` "
            f"field for those runs. Real tokenizer counts land when "
            f"the run was driven through llama-cpp / OpenAI / "
            f"Anthropic adapters with usage reporting._"
        )
    unknown = next((r for r in rows if r["model"] == "unknown"), None)
    if unknown:
        lines.append("")
        lines.append(
            f"_The ``unknown`` row aggregates "
            f"{unknown['run_count']} run(s) from before "
            f"``model_name`` was stamped into ``summary.json`` "
            f"(2026-05-27). Re-run those to attribute them._"
        )

    # ── Archived runs (pre-1.1 corpus) ─────────────────────────
    # Surface the score each model last earned on the 1.0 corpus so
    # the reader knows what the model used to look like — and which
    # models still need re-benching on 1.1 to rejoin the active
    # leaderboard. Only shown when archived data exists for at least
    # one model that's also currently installed (otherwise it's just
    # noise about deleted models).
    if archived_rows:
        # Only keep archived entries for models that:
        #   1. Are still on disk (otherwise it's noise about deleted
        #      models), AND
        #   2. Do NOT have any v1.1 data yet — i.e. they truly need
        #      re-benching. A model that already has a v1.1 run is on
        #      the active leaderboard above, so re-listing it here
        #      under its old score is just redundant noise.
        installed = _installed_model_stems(
            repo=pathlib.Path(__file__).resolve().parents[3]
        )
        models_with_current = {r["model"] for r in rows}
        visible_archived = [
            r for r in archived_rows
            if (not installed or r["model"] in installed)
            and r["model"] not in models_with_current
        ]
        if visible_archived:
            lines += [
                "",
                "## Archived runs (pre-1.1 corpus)",
                "",
                f"These models have only pre-{_CURRENT_BENCH_VERSION} "
                "(51-case) data — older corpus that lacked the safety / "
                "hallucination / cross-turn tiers. Scores aren't "
                "comparable with the active leaderboard above. **Re-run "
                "them on the current corpus to rejoin the rankings** — "
                "the sweep does this automatically once you bench the "
                "model again.",
                "",
                "| Model | Last v1.0 Score | Best route% | Latest run |",
                "|---|---:|---:|---|",
            ]
            for r in sorted(visible_archived,
                            key=lambda x: -x.get("best_route_pct", 0)):
                lines.append(
                    f"| `{r['model']}` | "
                    f"{r.get('score_display', '—')} | "
                    f"{r.get('best_route_pct', 0):.1f}% | "
                    f"{_compact_ts(r.get('latest_ts', ''))} |"
                )

    return "\n".join(lines) + "\n"


# ── path helper ───────────────────────────────────────────────


def _repo_root() -> pathlib.Path:
    """Walk up from this file to find the repo root (the dir that
    contains ``benchmark/``). Works for editable + installed wheels."""
    here = pathlib.Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "dev/benchmark").is_dir():
            return parent
    # Fallback for unusual layouts.
    return here.parents[3]


__all__ = [
    "_cmd_bench_history_argv",
    "render_history_md",
    "write_history_md",
]
