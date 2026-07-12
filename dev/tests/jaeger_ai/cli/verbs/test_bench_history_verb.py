"""``jaeger bench history`` — rolling leaderboard verb.

Pins the data-source parsing + aggregation contract. Each test
builds a fake ``benchmark/`` tree under ``tmp_path``, monkey-patches
``_repo_root`` to point at it, then checks the verb's output.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from jaeger_ai.cli.verbs import bench_history_verb as bhv


# ── fixtures ──────────────────────────────────────────────────


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """Build a minimal ``benchmark/`` tree the verb can scan."""
    bench = tmp_path / "dev/benchmark"
    (bench / "sweep").mkdir(parents=True)
    (bench / "results").mkdir()
    monkeypatch.setattr(bhv, "_repo_root", lambda: tmp_path)
    return tmp_path


def _write_sweep_row(bench_dir: pathlib.Path, **fields) -> None:
    path = bench_dir / "sweep" / "sweep_rows.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_flat_summary(
    bench_dir: pathlib.Path,
    ts: str,
    *,
    nested_under: str | None = None,
    use_new_filename: bool = False,
    **fields,
) -> None:
    """Write a summary file into the flat tree.

    ``nested_under`` selects the directory layout (new
    ``flat/<model>/<ts>/`` when set, legacy ``flat/<ts>/`` when None).

    ``use_new_filename`` selects the FILENAME convention — when True,
    write ``<model>-<ts>-summary.json``; when False, the legacy
    ``summary.json``. The walker handles both.
    """
    if nested_under:
        run = bench_dir / "results" / nested_under / ts
        prefix = f"{nested_under}-{ts}"
    else:
        run = bench_dir / "results" / ts
        prefix = f"unknown-{ts}"
    run.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}-summary.json" if use_new_filename else "summary.json"
    (run / filename).write_text(
        json.dumps(fields), encoding="utf-8",
    )


# ── _family_of ────────────────────────────────────────────────


def test_family_of_recognises_known_families():
    assert bhv._family_of("gemma-4-26B-A4B-it-Q4") == "gemma"
    assert bhv._family_of("Qwen3.6-35B-A3B") == "qwen"
    assert bhv._family_of("Llama-3.2-3B") == "llama"
    assert bhv._family_of("Ministral-3-14B") == "mistral"
    assert bhv._family_of("phi-4-mini") == "phi"
    assert bhv._family_of("weird-novel-model") == "other"
    assert bhv._family_of("") == "other"


# ── _from_sweep_jsonl ─────────────────────────────────────────


def test_sweep_jsonl_parses_rows_and_skips_zero_case_runs(fake_repo):
    """A sweep row with ``cases > 0`` becomes a leaderboard entry.
    Zero-case rows (errors / timeouts) skip — visible in the raw
    jsonl but not in the ranked table."""
    bench = fake_repo / "dev/benchmark"
    _write_sweep_row(
        bench, name="gemma-4-26B-A4B", cases=34, route_ok=23,
        answer_ok=14, elapsed_s=265.0, p50_turn_s=5.6,
        ts="2026-05-24T17:27:00",
    )
    _write_sweep_row(
        bench, name="Qwen3.6-27B", cases=0, route_ok=0,
        error="timeout", ts="2026-05-24T15:13:30",
    )
    entries = list(bhv._from_sweep_jsonl(fake_repo))
    assert len(entries) == 1
    e = entries[0]
    assert e["model"] == "gemma-4-26b-a4b"
    assert e["family"] == "gemma"
    assert e["source"] == "sweep"
    assert e["cases"] == 34
    # 23/34 = 67.6%
    assert e["route_pct"] == pytest.approx(67.6, abs=0.1)
    assert e["p50_s"] == pytest.approx(5.6)


def test_sweep_jsonl_handles_missing_file(fake_repo):
    """No sweep_rows.jsonl → empty iterator, no crash."""
    out = list(bhv._from_sweep_jsonl(fake_repo))
    assert out == []


def test_sweep_jsonl_skips_corrupt_lines(fake_repo):
    """Mid-file garbage skipped; valid lines still parsed."""
    bench = fake_repo / "dev/benchmark"
    sweep_jsonl = bench / "sweep" / "sweep_rows.jsonl"
    with sweep_jsonl.open("w", encoding="utf-8") as fh:
        fh.write('{"name": "ok", "cases": 5, "route_ok": 4}\n')
        fh.write("not json at all\n")
        fh.write('{"name": "ok2", "cases": 10, "route_ok": 8}\n')
    out = list(bhv._from_sweep_jsonl(fake_repo))
    assert [e["model"] for e in out] == ["ok", "ok2"]


# ── _from_flat_summaries ──────────────────────────────────────


def test_flat_summaries_parse_modern_format(fake_repo):
    """A modern summary.json (with ``model_name`` + metrics block)
    becomes a leaderboard entry."""
    bench = fake_repo / "dev/benchmark"
    _write_flat_summary(
        bench, "20260527-100000",
        model_name="gemma-4-E4B-it-Q4_K_M",
        model_path="/x/y.gguf",
        run_id="20260527-100000",
        total=51, passed=47, pass_rate=0.922,
        routing_total=49, routing_passed=47,
        elapsed_s=296.0, wall_s=311.0,
        metrics={
            "avg_latency_s": 6.0, "p50_latency_s": 1.3,
            "p95_latency_s": 25.0, "answer_tokens_per_sec": 12.5,
            "answer_tokens_source": "tokenizer",
        },
    )
    entries = list(bhv._from_flat_summaries(fake_repo))
    assert len(entries) == 1
    e = entries[0]
    assert e["model"] == "gemma-4-e4b-it-q4-k-m"
    assert e["family"] == "gemma"
    assert e["source"] == "flat"
    assert e["pass_rate"] == 0.922
    assert e["p50_s"] == 1.3
    assert e["p95_s"] == 25.0
    assert e["tokens_per_sec"] == 12.5
    assert e["tokens_source"] == "tokenizer"
    # 47/49 routing
    assert e["route_pct"] == pytest.approx(95.9, abs=0.1)


def test_flat_summaries_handle_pre_stamp_runs(fake_repo):
    """Runs from before model_name was stamped land in the
    'unknown' bucket — visible but flagged."""
    bench = fake_repo / "dev/benchmark"
    _write_flat_summary(
        bench, "20260525-105743",
        total=10, passed=9, pass_rate=0.9,
        routing_total=9, routing_passed=8,
        metrics={"p50_latency_s": 2.0},
    )
    entries = list(bhv._from_flat_summaries(fake_repo))
    assert len(entries) == 1
    assert entries[0]["model"] == "unknown"


def test_flat_summaries_skips_dirs_without_summary(fake_repo):
    """A run dir with rows.jsonl but no summary.json is incomplete
    (interrupted run). Skip silently."""
    bench = fake_repo / "dev/benchmark"
    (bench / "results" / "20260527-broken").mkdir()
    out = list(bhv._from_flat_summaries(fake_repo))
    assert out == []


def test_flat_summaries_walks_new_nested_layout(fake_repo):
    """2026-05-27: flat output restructured from
    ``flat/<ts>/`` to ``flat/<model>/<ts>/``. The walker must
    descend one level when the immediate child of flat/ has no
    summary.json (i.e. it's a model-named bucket, not a
    timestamped run)."""
    bench = fake_repo / "dev/benchmark"
    _write_flat_summary(
        bench, "20260527-110000",
        nested_under="gemma-4-E4B-it-Q4_K_M",
        model_name="gemma-4-E4B-it-Q4_K_M",
        run_id="20260527-110000",
        total=51, passed=47, pass_rate=0.92,
        routing_total=49, routing_passed=47,
        metrics={"p50_latency_s": 1.3},
    )
    _write_flat_summary(
        bench, "20260527-110500",
        nested_under="gemma-4-26B-A4B-it-Q4_K_M",
        model_name="gemma-4-26B-A4B-it-Q4_K_M",
        run_id="20260527-110500",
        total=51, passed=45, pass_rate=0.88,
        routing_total=49, routing_passed=45,
        metrics={"p50_latency_s": 2.5},
    )
    entries = list(bhv._from_flat_summaries(fake_repo))
    models = sorted(e["model"] for e in entries)
    # Both slugs dash-normalised — consistent canonical form (no
    # underscore/dash split that would double-count a model).
    assert models == ["gemma-4-26b-a4b-it-q4-k-m", "gemma-4-e4b-it-q4-k-m"]
    e4b = next(e for e in entries if e["model"] == "gemma-4-e4b-it-q4-k-m")
    # ``run_dir`` should reflect the new layout.
    assert "gemma-4-E4B-it-Q4_K_M" in e4b["run_dir"]
    assert "20260527-110000" in e4b["run_dir"]


def test_flat_summaries_finds_new_filename_convention(fake_repo):
    """2026-05-27 evening: filenames switched from ``summary.json``
    to ``<model>-<ts>-summary.json`` for self-identifying artifacts.
    The walker must find both names so the transition is silent."""
    bench = fake_repo / "dev/benchmark"
    _write_flat_summary(
        bench, "20260527-130000",
        nested_under="gemma-4-E4B-it-Q4_K_M",
        use_new_filename=True,
        model_name="gemma-4-E4B-it-Q4_K_M",
        run_id="20260527-130000",
        total=51, passed=47, pass_rate=0.92,
        routing_total=49, routing_passed=47,
        metrics={"p50_latency_s": 1.3,
                 "answer_tokens_per_sec": 20.0,
                 "answer_tokens_source": "tokenizer"},
    )
    entries = list(bhv._from_flat_summaries(fake_repo))
    assert len(entries) == 1
    assert entries[0]["model"] == "gemma-4-e4b-it-q4-k-m"
    assert entries[0]["tokens_per_sec"] == 20.0


def test_flat_summaries_handles_mixed_old_and_new_layouts(fake_repo):
    """During the transition some runs are at ``flat/<ts>/`` and
    others at ``flat/<model>/<ts>/``. The walker must read both."""
    bench = fake_repo / "dev/benchmark"
    # Legacy timestamp-only (no model attribution).
    _write_flat_summary(
        bench, "20260525-100000",
        run_id="20260525-100000",
        total=10, passed=8, pass_rate=0.8,
        routing_total=8, routing_passed=7,
        metrics={"p50_latency_s": 1.0},
    )
    # New nested.
    _write_flat_summary(
        bench, "20260527-110000",
        nested_under="gemma-4-E4B-it-Q4_K_M",
        model_name="gemma-4-E4B-it-Q4_K_M",
        run_id="20260527-110000",
        total=51, passed=47, pass_rate=0.92,
        routing_total=49, routing_passed=47,
        metrics={"p50_latency_s": 1.3},
    )
    entries = list(bhv._from_flat_summaries(fake_repo))
    assert len(entries) == 2
    # The old run lands in 'unknown', the new one gets a canonical id.
    models = {e["model"] for e in entries}
    assert models == {"unknown", "gemma-4-e4b-it-q4-k-m"}


# ── _aggregate_by_model ───────────────────────────────────────


def test_aggregate_picks_best_route_per_model(fake_repo):
    """Multi-run model: best_route_pct is the MAX across runs;
    latest_p50 tracks the most recent run."""
    entries = [
        {"model": "gemma-4-E4B", "family": "gemma", "source": "flat",
         "ts": "20260525-100000", "pass_rate": 0.8, "route_pct": 80.0,
         "p50_s": 1.5, "p95_s": 20.0, "avg_latency_s": 6.0,
         "tokens_per_sec": 10.0, "tokens_source": "tokenizer",
         "cases": 51, "run_dir": "x"},
        {"model": "gemma-4-E4B", "family": "gemma", "source": "flat",
         "ts": "20260527-100000", "pass_rate": 0.92, "route_pct": 92.0,
         "p50_s": 1.3, "p95_s": 25.0, "avg_latency_s": 5.0,
         "tokens_per_sec": 12.0, "tokens_source": "tokenizer",
         "cases": 51, "run_dir": "x"},
    ]
    out = bhv._aggregate_by_model(entries)
    assert len(out) == 1
    r = out[0]
    assert r["model"] == "gemma-4-E4B"
    assert r["best_route_pct"] == 92.0
    assert r["best_pass_rate"] == 0.92
    # ``latest_*`` from the newer ts row.
    assert r["latest_p50_s"] == 1.3
    assert r["latest_p95_s"] == 25.0
    assert r["latest_ts"] == "20260527-100000"
    assert r["run_count"] == 2


def test_aggregate_sort_order_route_desc_then_p50_asc(fake_repo):
    """Higher route% wins; ties broken by faster p50."""
    entries = [
        {"model": "slow_top", "family": "x", "source": "flat",
         "ts": "20260527", "pass_rate": 0.9, "route_pct": 90.0,
         "p50_s": 10.0, "p95_s": 0, "avg_latency_s": 0,
         "tokens_per_sec": 0, "tokens_source": "t", "cases": 1,
         "run_dir": "x"},
        {"model": "fast_top", "family": "x", "source": "flat",
         "ts": "20260527", "pass_rate": 0.9, "route_pct": 90.0,
         "p50_s": 1.0, "p95_s": 0, "avg_latency_s": 0,
         "tokens_per_sec": 0, "tokens_source": "t", "cases": 1,
         "run_dir": "x"},
        {"model": "mediocre", "family": "x", "source": "flat",
         "ts": "20260527", "pass_rate": 0.7, "route_pct": 70.0,
         "p50_s": 0.5, "p95_s": 0, "avg_latency_s": 0,
         "tokens_per_sec": 0, "tokens_source": "t", "cases": 1,
         "run_dir": "x"},
    ]
    out = bhv._aggregate_by_model(entries)
    names = [r["model"] for r in out]
    # 90% × 2 first (fast_top before slow_top), then 70%.
    assert names == ["fast_top", "slow_top", "mediocre"]


def test_aggregate_empty_input_returns_empty(fake_repo):
    assert bhv._aggregate_by_model([]) == []


# ── _render ───────────────────────────────────────────────────


def test_render_produces_markdown_table(fake_repo):
    rows = [
        {"model": "gemma-4-E4B", "family": "gemma",
         "best_route_pct": 92.0, "best_pass_rate": 0.92,
         "latest_p50_s": 1.3, "latest_p95_s": 25.0,
         "latest_tokens_per_sec": 12.5, "latest_tokens_source": "tokenizer",
         "latest_route_pct": 92.0, "latest_ts": "20260527-100000",
         "latest_cases": 51, "run_count": 2},
    ]
    md = bhv._render(rows, all_entries=[], total_entries=2)
    assert "# Jaeger-OS Benchmark Leaderboard" in md
    assert "gemma-4-E4B" in md
    assert "92.0%" in md
    assert "Runs" in md
    # Compact timestamp.
    assert "2026-05-27" in md


def test_render_empty_says_no_artifacts():
    md = bhv._render([], all_entries=[], total_entries=0)
    assert "No bench artifacts found" in md
    assert "jaeger bench run" in md


def test_render_emits_three_sections_when_data_present():
    """Output has three sections: per-model leaderboard, top-10
    all-time, full chronological log."""
    rows = [
        {"model": "m1", "family": "f",
         "best_route_pct": 90, "best_pass_rate": 0.9,
         "latest_p50_s": 1.0, "latest_p95_s": 2.0,
         "latest_tokens_per_sec": 10.0,
         "latest_tokens_source": "tokenizer",
         "latest_route_pct": 90, "latest_ts": "20260527-100000",
         "latest_cases": 51, "run_count": 1},
    ]
    entries = [
        {"model": "m1", "family": "f", "source": "flat",
         "ts": "20260527-100000", "pass_rate": 0.9, "route_pct": 90.0,
         "p50_s": 1.0, "p95_s": 2.0, "avg_latency_s": 1.2,
         "tokens_per_sec": 10.0, "tokens_source": "tokenizer",
         "cases": 51, "run_dir": "x"},
    ]
    md = bhv._render(rows, all_entries=entries, total_entries=1)
    assert "## Per-model leaderboard" in md
    assert "## Top 10 all-time best runs" in md
    assert "## Full chronological log" in md


def test_render_chronological_marks_peak_runs():
    """A run that ties the model's all-time best gets flagged
    ``peak``; lesser runs show the delta."""
    entries = [
        {"model": "m1", "family": "f", "source": "flat",
         "ts": "20260525-120000", "pass_rate": 0.8, "route_pct": 80.0,
         "p50_s": 2.0, "p95_s": 5.0, "avg_latency_s": 3.0,
         "tokens_per_sec": 10.0, "tokens_source": "tokenizer",
         "cases": 51, "run_dir": "x"},
        {"model": "m1", "family": "f", "source": "flat",
         "ts": "20260527-100000", "pass_rate": 0.92, "route_pct": 92.0,
         "p50_s": 1.0, "p95_s": 2.0, "avg_latency_s": 1.2,
         "tokens_per_sec": 10.0, "tokens_source": "tokenizer",
         "cases": 51, "run_dir": "x"},
    ]
    rows = [{
        "model": "m1", "family": "f",
        "best_route_pct": 92, "best_pass_rate": 0.92,
        "latest_p50_s": 1.0, "latest_p95_s": 2.0,
        "latest_tokens_per_sec": 10.0,
        "latest_tokens_source": "tokenizer",
        "latest_route_pct": 92, "latest_ts": "20260527-100000",
        "latest_cases": 51, "run_count": 2,
    }]
    md = bhv._render(rows, all_entries=entries, total_entries=2)
    # The 92% run is the peak; -12.0pp marks the earlier 80% run.
    assert "**peak**" in md
    assert "-12.0pp" in md


def test_render_top10_caps_to_ten_entries():
    """The top-10 section shows at most 10 runs even if more exist."""
    entries = [
        {"model": f"m{i}", "family": "f", "source": "flat",
         "ts": f"20260527-{i:06d}",
         "pass_rate": 0.5, "route_pct": float(50 + i),
         "p50_s": 1.0, "p95_s": 2.0, "avg_latency_s": 1.0,
         "tokens_per_sec": 5.0, "tokens_source": "tokenizer",
         "cases": 51, "run_dir": "x"}
        for i in range(15)
    ]
    rows = [{
        "model": "m0", "family": "f",
        "best_route_pct": 64, "best_pass_rate": 0.5,
        "latest_p50_s": 1.0, "latest_p95_s": 2.0,
        "latest_tokens_per_sec": 5.0,
        "latest_tokens_source": "tokenizer",
        "latest_route_pct": 64, "latest_ts": "20260527-000000",
        "latest_cases": 51, "run_count": 15,
    }]
    md = bhv._render(rows, all_entries=entries, total_entries=15)
    # Find the top-10 section.
    top_section = md.split("## Top 10")[1].split("## Full")[0]
    # Count the table rows (lines starting with "| 1 |", "| 2 |", ...).
    row_count = sum(1 for ln in top_section.splitlines()
                    if ln.startswith("| ") and "%" in ln
                    and not ln.startswith("| # |"))
    assert row_count == 10


def test_render_flags_whitespace_estimate_rows():
    """When a model's latest run used the whitespace estimate, the
    footer calls it out so the operator knows the tok/s column is
    approximate for those rows."""
    rows = [
        {"model": "x", "family": "y",
         "best_route_pct": 50, "best_pass_rate": 0.5,
         "latest_p50_s": 1.0, "latest_p95_s": 1.0,
         "latest_tokens_per_sec": 10.0,
         "latest_tokens_source": "whitespace_estimate",
         "latest_route_pct": 50, "latest_ts": "20260527-100000",
         "latest_cases": 1, "run_count": 1},
    ]
    md = bhv._render(rows, all_entries=[], total_entries=1)
    assert "whitespace-estimate" in md.lower() or "whitespace_estimate" in md


# ── _cmd_bench_history_argv ───────────────────────────────────


def test_history_help_returns_zero(capsys):
    rc = bhv._cmd_bench_history_argv(["-h"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "bench history" in err
    assert "--write" in err
    assert "--family" in err


def test_history_empty_repo_prints_no_artifacts(fake_repo, capsys):
    """No bench data anywhere → renders the "no artifacts" placeholder
    + rc=0 (calling the verb on a fresh checkout shouldn't be a fail)."""
    rc = bhv._cmd_bench_history_argv([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No bench artifacts found" in out


def test_history_reads_both_sources_and_renders(fake_repo, capsys):
    """Sweep + flat sources both contribute to the leaderboard."""
    bench = fake_repo / "dev/benchmark"
    _write_sweep_row(
        bench, name="qwen-old", cases=34, route_ok=30,
        answer_ok=15, elapsed_s=500.0, p50_turn_s=10.0,
        ts="2026-05-24T17:00:00",
    )
    _write_flat_summary(
        bench, "20260527-100000",
        model_name="gemma-new",
        run_id="20260527-100000",
        total=51, passed=48, pass_rate=0.94,
        routing_total=50, routing_passed=49,
        metrics={"p50_latency_s": 1.5, "p95_latency_s": 25.0,
                 "answer_tokens_per_sec": 15.0,
                 "answer_tokens_source": "tokenizer"},
    )
    # --all + --min-cases 0: this test mixes an old-dated sweep row
    # with a new flat run to prove BOTH sources render. The default
    # since/min-cases filters would drop the old + small rows.
    rc = bhv._cmd_bench_history_argv(["--all", "--min-cases", "0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "qwen-old" in out
    assert "gemma-new" in out
    # gemma-new outranks qwen-old on route% (49/50=98% > 30/34=88%).
    assert out.index("gemma-new") < out.index("qwen-old")


def test_history_family_filter(fake_repo, capsys):
    """``--family gemma`` shows only gemma rows."""
    bench = fake_repo / "dev/benchmark"
    _write_sweep_row(bench, name="qwen-x", cases=10, route_ok=10,
                     ts="2026-05-24")
    _write_sweep_row(bench, name="gemma-y", cases=10, route_ok=9,
                     ts="2026-05-24")
    rc = bhv._cmd_bench_history_argv(
        ["--family", "gemma", "--all", "--min-cases", "0"],
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "gemma-y" in out
    assert "qwen-x" not in out


def test_history_top_n_caps_leaderboard(fake_repo, capsys):
    """``--top N`` caps the **per-model leaderboard** section to N
    rows. The chronological + all-time-top sections still show
    every run — they're complementary views (today's snapshot vs.
    the full record)."""
    bench = fake_repo / "dev/benchmark"
    _write_sweep_row(bench, name="a", cases=10, route_ok=10, ts="t")
    _write_sweep_row(bench, name="b", cases=10, route_ok=9,  ts="t")
    _write_sweep_row(bench, name="c", cases=10, route_ok=8,  ts="t")
    rc = bhv._cmd_bench_history_argv(
        ["--top", "1", "--all", "--min-cases", "0"],
    )
    out = capsys.readouterr().out
    assert rc == 0
    # Per-model leaderboard section: only the top entry.
    leaderboard = out.split("## Per-model leaderboard")[1].split("##")[0]
    assert "| `a` |" in leaderboard
    assert "| `b` |" not in leaderboard
    assert "| `c` |" not in leaderboard
    # Chronological + top-10 sections still surface all runs — the
    # --top flag is about the leaderboard summary, not the raw log.
    assert "| `b` |" in out  # appears in chronological
    assert "| `c` |" in out


def test_history_write_persists_history_md(fake_repo, capsys):
    bench = fake_repo / "dev/benchmark"
    _write_sweep_row(bench, name="x", cases=10, route_ok=10, ts="t")
    rc = bhv._cmd_bench_history_argv(["--write", "--all", "--min-cases", "0"])
    assert rc == 0
    written = fake_repo / "dev/benchmark" / "HISTORY.md"
    assert written.exists()
    assert "# Jaeger-OS Benchmark Leaderboard" in written.read_text(encoding="utf-8")


# ── --since / --min-cases filters (2026-05-27) ───────────────


def test_since_filter_excludes_old_runs(fake_repo, capsys):
    """Default --since + bench-version filter drops pre-cutoff (1.0)
    runs; --all + --include-uninstalled bring them back. Old corpus
    (51-case 1.0) isn't apples-to-apples with the current full corpus."""
    bench = fake_repo / "dev/benchmark"
    # sweep_rows infer version from CASE COUNT (metadata-only path): 51 -> 1.0
    # (old, dropped), 77 -> current full corpus (ranked).
    _write_sweep_row(bench, name="may28-model", cases=51, route_ok=40,
                     ts="2026-05-28T10:00:00")
    _write_sweep_row(bench, name="may30-model", cases=77, route_ok=54,
                     ts="2026-05-30T10:00:00")
    # Default cutoff is 2026-05-29 → only may30 (current corpus) shows.
    rc = bhv._cmd_bench_history_argv([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "may30-model" in out
    assert "may28-model" not in out
    # --all includes both.
    rc = bhv._cmd_bench_history_argv(["--all"])
    out = capsys.readouterr().out
    assert "may28-model" in out
    assert "may30-model" in out


def test_since_explicit_date(fake_repo, capsys):
    """An explicit --since overrides the default cutoff.
    Both rows are current-corpus so the bench-version filter keeps them;
    --since is the relevant filter under test."""
    bench = fake_repo / "dev/benchmark"
    # 77 cases -> current corpus (sweep rows infer version from case count).
    _write_sweep_row(bench, name="m1", cases=77, route_ok=40,
                     ts="2026-05-30T10:00:00")
    _write_sweep_row(bench, name="m2", cases=77, route_ok=48,
                     ts="2026-06-01T10:00:00")
    rc = bhv._cmd_bench_history_argv(["--since", "2026-05-31"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "m2" in out
    assert "m1" not in out


def test_min_cases_excludes_mini_benches(fake_repo, capsys):
    """Debugging mini-benches (cases < 50) pollute 'best route%' with
    trivial 100%s. Default --min-cases 50 drops them; the full run
    stays."""
    bench = fake_repo / "dev/benchmark"
    # Both runs explicitly tagged 1.1 so the bench-version filter
    # doesn't pre-drop the mini-bench — this test is about the
    # min-cases filter specifically.
    _write_flat_summary(
        bench, "20260530-100000", nested_under="real-model",
        model_name="real-model", run_id="20260530-100000",
        total=59, passed=45, pass_rate=0.76,
        routing_total=49, routing_passed=45,
        metrics={"p50_latency_s": 2.0},
        benchmark_version=bhv._CURRENT_BENCH_VERSION,
    )
    _write_flat_summary(
        bench, "20260530-110000", nested_under="real-model",
        model_name="real-model", run_id="20260530-110000",
        total=3, passed=3, pass_rate=1.0,
        routing_total=3, routing_passed=3,  # mini-bench, trivial 100%
        metrics={"p50_latency_s": 1.0},
        benchmark_version=bhv._CURRENT_BENCH_VERSION,
    )
    rc = bhv._cmd_bench_history_argv([])  # default min-cases 50
    out = capsys.readouterr().out
    assert rc == 0
    # Best route% should reflect the 59-case run (45/49≈91.8%), NOT
    # the mini-bench's trivial 100%.
    leaderboard = out.split("## Per-model leaderboard")[1].split("##")[0]
    assert "100.0%" not in leaderboard, (
        "the 3-case mini-bench's 100% leaked into the leaderboard — "
        "min-cases filter should have excluded it"
    )
    # With --min-cases 0 the mini-bench counts and best jumps to 100%.
    rc = bhv._cmd_bench_history_argv(["--min-cases", "0"])
    out = capsys.readouterr().out
    leaderboard = out.split("## Per-model leaderboard")[1].split("##")[0]
    assert "100.0%" in leaderboard


def test_ts_to_date_handles_both_formats():
    assert bhv._ts_to_date("2026-05-24T17:27:00") == "2026-05-24"
    assert bhv._ts_to_date("20260527-122229") == "2026-05-27"
    assert bhv._ts_to_date("") == ""
    assert bhv._ts_to_date("garbage") == ""


def test_write_history_md_silent_helper(fake_repo, capsys):
    """``write_history_md`` regenerates HISTORY.md with NO stdout
    noise (it's the auto-update hook a bench run fires) and returns
    the path. Default filters apply (current-gen, full-corpus)."""
    bench = fake_repo / "dev/benchmark"
    _write_flat_summary(
        bench, "20260527-120000", nested_under="m1",
        model_name="m1", run_id="20260527-120000",
        total=51, passed=48, pass_rate=0.94,
        routing_total=49, routing_passed=48,
        metrics={"p50_latency_s": 2.0},
    )
    out_path = bhv.write_history_md(fake_repo)
    captured = capsys.readouterr()
    assert out_path is not None
    assert out_path.exists()
    assert "# Jaeger-OS Benchmark Leaderboard" in out_path.read_text(encoding="utf-8")
    # Silent: nothing printed to stdout/stderr.
    assert captured.out == ""
    assert captured.err == ""


def test_write_history_md_never_raises(monkeypatch):
    """The auto-update hook must be fire-and-forget — if anything goes
    wrong (e.g. repo not found), it returns None, never raises, so a
    bench run's exit status is unaffected."""
    monkeypatch.setattr(
        bhv, "_collect_entries",
        lambda repo: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # Should swallow the error and return None.
    assert bhv.write_history_md(pathlib.Path("/nonexistent/repo")) is None


def test_unknown_bucket_excluded_by_default(fake_repo, capsys):
    """Runs with no model_name (the 'unknown' bucket) can't be ranked
    against named models — drop them by default. ``--include-unknown``
    brings them back."""
    bench = fake_repo / "dev/benchmark"
    # An attributed run + an unattributed one, both today + full corpus.
    _write_flat_summary(
        bench, "20260530-100000", nested_under="real-model",
        model_name="real-model", run_id="20260530-100000",
        total=59, passed=45, pass_rate=0.76,
        routing_total=49, routing_passed=45,
        metrics={"p50_latency_s": 2.0},
        benchmark_version=bhv._CURRENT_BENCH_VERSION,
    )
    _write_flat_summary(
        bench, "20260530-110000",   # no nested_under → 'unknown'
        run_id="20260530-110000",
        total=59, passed=40, pass_rate=0.68,
        routing_total=49, routing_passed=40,
        metrics={"p50_latency_s": 3.0},
        benchmark_version=bhv._CURRENT_BENCH_VERSION,
    )
    # Default: unknown excluded.
    rc = bhv._cmd_bench_history_argv([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "real-model" in out
    assert "unknown" not in out.split("## Per-model leaderboard")[1].split("##")[0]
    # Opt-in: unknown shown.
    rc = bhv._cmd_bench_history_argv(["--include-unknown"])
    out = capsys.readouterr().out
    assert "unknown" in out


# ── dispatcher integration ───────────────────────────────────


def test_cli_bench_dispatcher_routes_history(monkeypatch):
    from jaeger_ai.cli.verbs import dispatch as cli
    captured: list[list[str]] = []
    def _spy(argv):
        captured.append(argv)
        return 0
    monkeypatch.setattr(
        "jaeger_ai.cli.verbs.bench_history_verb._cmd_bench_history_argv", _spy,
    )
    rc = cli._cmd_bench(["history", "--top", "5"])
    assert rc == 0
    assert captured == [["--top", "5"]]
