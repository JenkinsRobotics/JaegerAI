# Jaeger-OS Benchmark Leaderboard

_Generated 2026-08-21T16:40:07 from 70 run(s) across `dev/benchmark/sweep/` and `dev/benchmark/flat/` — showing runs on/after **2026-05-29** (current benchmark generation). Filtered out **1** entry for models no longer on disk — historical data preserved in ``dev/benchmark/flat/``._

**Bench corpus version: 1.3** (cutoff 2026-05-29). The leaderboard ranks only runs of this version so the comparison stays apples-to-apples; older 1.0 (51-case) runs are archived and shown separately at the bottom of the report.

## Per-model leaderboard

<details><summary><i>1 hidden uninstalled model</i></summary>

These models have bench history but their ``.gguf`` files are no longer in ``~/.lmstudio/models``. Run ``jaeger bench history --write --include-uninstalled`` to surface them again.

- `gemma-4-26b-a4b-it-qat-q4-0`

</details>

``Score`` is dead simple: **``passed / total``** from the latest run. Every case worth the same 1/total — pass 50/59 → 84.7%, no tier weighting, no hidden math. The per-tier columns are informational breakdowns of WHICH cases passed: ``Deep-think`` = code / multistep / recovery (what a coding agent needs); ``Real-time`` = routing (what a fast agent needs); ``Multi-turn`` = multiturn / cross-turn (stateful conversations); ``Safety`` = refusal / no-hallucination cases. Latest-run figures, sorted by Score.

**Methodology — ideal state vs baseline.** Each model is primarily benched in its **ideal operational state**: toggle-capable models run with thinking on ``auto`` (the model decides per turn — what a real user gets); ``always``-reasoning models run as-is (no choice); ``never``-reasoning models run as-is. Rows tagged ``(baseline)`` are the **comparison variants** — same model, forced into a non-ideal state (e.g. an ``auto`` model forced to ``off`` for direct-mode benchmarking). Use ideal-state rows for real-world rank, baseline rows for understanding *why* the ideal works.

| # | Model | Mode | Family | **Score** | Deep-think | Real-time | Multi-turn | Agentic | Safety | Best route% | Latest elapsed | Tokens/task | Latest run | Runs |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 1 | `gemma-4-e4b-it-q4-k-m` | 🧠 auto | gemma | **98.8%** | — | — | — | — | — | 100.0% | 7m20s | 106 | 2026-08-05 09:06 | 58 |

## Top 10 all-time best runs

Sorted by routing % (then p50 asc). A single great run doesn't make a model great, but tracking peaks tells you what's achievable on this hardware.

| # | Date | Model | Route% | p50 s | p95 s | TPS | Cases | Source |
|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 2026-07-12 21:55 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.53 | 28.32 | 17.8 | 81 | flat |
| 2 | 2026-07-12 22:10 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.54 | 23.44 | 21.3 | 81 | flat |
| 3 | 2026-07-12 16:34 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.54 | 32.92 | 22.4 | 81 | flat |
| 4 | 2026-07-12 21:04 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.55 | 26.16 | 20.0 | 81 | flat |
| 5 | 2026-08-04 10:08 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.56 | 13.46 | 20.3 | 81 | flat |
| 6 | 2026-07-12 22:30 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.57 | 21.91 | 21.3 | 81 | flat |
| 7 | 2026-08-04 23:56 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.57 | 22.55 | 21.0 | 81 | flat |
| 8 | 2026-08-04 20:10 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.61 | 15.39 | 18.7 | 81 | flat |
| 9 | 2026-08-05 09:06 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.68 | 22.35 | 20.3 | 81 | flat |
| 10 | 2026-08-04 22:59 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.70 | 23.13 | 20.3 | 81 | flat |

## Full chronological log

Every run we have data for (70 total), newest first. ``vs peak`` shows the route% delta from this model's all-time best (0.0% = this run IS the peak).

| Date | Model | Route% | p50 s | TPS | Cases | vs peak | Source |
|---|---|---:|---:|---:|---:|---:|---|
| 2026-08-05 09:06 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.68 | 20.3 | 81 | **peak** | flat |
| 2026-08-04 23:56 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.57 | 21.0 | 81 | **peak** | flat |
| 2026-08-04 22:59 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.70 | 20.3 | 81 | **peak** | flat |
| 2026-08-04 21:25 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 3.42 | 16.0 | 81 | **peak** | flat |
| 2026-08-04 20:10 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.61 | 18.7 | 81 | **peak** | flat |
| 2026-08-04 19:58 | `gemma-4-e4b-it-q4-k-m` | 98.5% | 2.55 | 22.1 | 81 | -1.5pp | flat |
| 2026-08-04 10:08 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.56 | 20.3 | 81 | **peak** | flat |
| 2026-08-04 08:38 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.78 | 19.4 | 81 | **peak** | flat |
| 2026-08-03 22:54 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.79 | 20.3 | 81 | **peak** | flat |
| 2026-07-12 22:30 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.57 | 21.3 | 81 | **peak** | flat |
| 2026-07-12 22:20 | `gemma-4-e4b-it-q4-k-m` | 98.5% | 2.54 | 20.1 | 81 | -1.5pp | flat |
| 2026-07-12 22:10 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.54 | 21.3 | 81 | **peak** | flat |
| 2026-07-12 21:55 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.53 | 17.8 | 81 | **peak** | flat |
| 2026-07-12 21:04 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.55 | 20.0 | 81 | **peak** | flat |
| 2026-07-12 16:34 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.54 | 22.4 | 81 | **peak** | flat |
| 2026-07-12 16:12 | `gemma-4-e4b-it-q4-k-m` | 98.4% | 2.71 | 17.0 | 81 | -1.6pp | flat |
| 2026-07-12 15:01 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.89 | 15.8 | 81 | **peak** | flat |
| 2026-07-11 22:53 | `gemma-4-e4b-it-q4-k-m` | 98.4% | 2.73 | 21.3 | 79 | -1.6pp | flat |
| 2026-07-06 09:07 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 3.23 | 16.6 | 81 | **peak** | flat |
| 2026-07-05 19:54 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.96 | 19.8 | 81 | **peak** | flat |
| 2026-07-05 18:27 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.99 | 19.8 | 81 | **peak** | flat |
| 2026-07-05 15:00 | `gemma-4-26b-a4b-it-qat-q4-0` | 96.8% | 2.78 | 16.3 | 81 | **peak** | flat |
| 2026-07-05 14:47 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 3.06 | 18.9 | 81 | **peak** | flat |
| 2026-07-05 14:07 | `gemma-4-26b-a4b-it-qat-q4-0` | 95.2% | 2.63 | 13.3 | 81 | -1.6pp | flat |
| 2026-07-05 13:53 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 3.12 | 21.1 | 81 | **peak** | flat |
| 2026-07-04 14:54 | `gemma-4-e4b-it-q4-k-m` | 98.4% | 3.16 | 22.5 | 81 | -1.6pp | flat |
| 2026-07-04 14:44 | `gemma-4-26b-a4b-it-qat-q4-0` | 96.8% | 2.73 | 13.4 | 81 | **peak** | flat |
| 2026-07-04 14:31 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.77 | 17.0 | 81 | **peak** | flat |
| 2026-07-04 14:03 | `gemma-4-e4b-it-q4-k-m` | 98.4% | 3.45 | 23.0 | 81 | -1.6pp | flat |
| 2026-07-04 13:52 | `gemma-4-26b-a4b-it-qat-q4-0` | 96.8% | 2.85 | 12.8 | 81 | **peak** | flat |
| 2026-07-04 13:37 | `gemma-4-e4b-it-q4-k-m` | 100.0% | 2.79 | 16.7 | 81 | **peak** | flat |
| 2026-07-04 13:09 | `gemma-4-26b-a4b-it-qat-q4-0` | 96.8% | 3.17 | 13.1 | 81 | **peak** | flat |
| 2026-07-04 12:55 | `gemma-4-e4b-it-q4-k-m` | 98.4% | 2.68 | 18.1 | 81 | -1.6pp | flat |
| 2026-07-04 00:00 | `gemma-4-26b-a4b-it-qat-q4-0` | 96.8% | 2.86 | 11.1 | 81 | **peak** | flat |
| 2026-07-03 23:44 | `gemma-4-e4b-it-q4-k-m` | 98.4% | 2.67 | 15.2 | 81 | -1.6pp | flat |
| 2026-07-03 23:11 | `gemma-4-26b-a4b-it-qat-q4-0` | 96.8% | 3.61 | 21.2 | 81 | **peak** | flat |
| 2026-07-03 22:54 | `gemma-4-e4b-it-q4-k-m` | 95.2% | 2.94 | 21.4 | 81 | -4.8pp | flat |
| 2026-07-03 20:30 | `gemma-4-26b-a4b-it-qat-q4-0` | 96.8% | 2.70 | 13.2 | 81 | **peak** | flat |
| 2026-07-03 20:15 | `gemma-4-e4b-it-q4-k-m` | 96.8% | 2.63 | 16.5 | 81 | -3.2pp | flat |
| 2026-07-03 18:05 | `gemma-4-26b-a4b-it-qat-q4-0` | 96.8% | 2.66 | 16.4 | 81 | **peak** | flat |
| 2026-07-03 17:52 | `gemma-4-e4b-it-q4-k-m` | 95.2% | 2.48 | 23.1 | 81 | -4.8pp | flat |
| 2026-07-03 17:01 | `gemma-4-26b-a4b-it-qat-q4-0` | 96.8% | 2.71 | 15.1 | 81 | **peak** | flat |
| 2026-07-03 16:48 | `gemma-4-e4b-it-q4-k-m` | 95.2% | 2.49 | 23.5 | 81 | -4.8pp | flat |
| 2026-07-03 14:50 | `gemma-4-26b-a4b-it-qat-q4-0` | 93.7% | 3.18 | 12.7 | 81 | -3.2pp | flat |
| 2026-07-03 14:34 | `gemma-4-e4b-it-q4-k-m` | 95.2% | 2.73 | 15.2 | 81 | -4.8pp | flat |
| 2026-07-03 13:02 | `gemma-4-e4b-it-q4-k-m` | 95.2% | 2.56 | 19.1 | 81 | -4.8pp | flat |
| 2026-07-03 11:49 | `gemma-4-e4b-it-q4-k-m` | 96.8% | 2.60 | 16.4 | 81 | -3.2pp | flat |
| 2026-07-03 01:50 | `gemma-4-e4b-it-q4-k-m` | 95.3% | 2.53 | 20.5 | 81 | -4.7pp | flat |
| 2026-07-03 01:39 | `gemma-4-e4b-it-q4-k-m` | 95.3% | 2.57 | 20.9 | 81 | -4.7pp | flat |
| 2026-07-03 01:26 | `gemma-4-e4b-it-q4-k-m` | 93.8% | 2.73 | 14.2 | 81 | -6.2pp | flat |
| 2026-07-02 23:14 | `gemma-4-e4b-it-q4-k-m` | 89.1% | 3.35 | 21.1 | 81 | -10.9pp | flat |
| 2026-07-02 22:49 | `gemma-4-e4b-it-q4-k-m` | 93.8% | 2.48 | 20.6 | 81 | -6.2pp | flat |
| 2026-07-02 22:30 | `gemma-4-e4b-it-q4-k-m` | 81.2% | 2.47 | 23.5 | 81 | -18.8pp | flat |
| 2026-07-02 22:10 | `gemma-4-e4b-it-q4-k-m` | 73.4% | 2.90 | 21.1 | 81 | -26.6pp | flat |
| 2026-07-02 20:55 | `gemma-4-e4b-it-q4-k-m` | 95.3% | 2.44 | 16.7 | 81 | -4.7pp | flat |
| 2026-07-02 20:30 | `gemma-4-e4b-it-q4-k-m` | 93.8% | 2.78 | 20.0 | 81 | -6.2pp | flat |
| 2026-07-02 19:22 | `gemma-4-e4b-it-q4-k-m` | 95.3% | 2.92 | 17.4 | 81 | -4.7pp | flat |
| 2026-07-02 16:21 | `gemma-4-e4b-it-q4-k-m` | 96.9% | 2.57 | 18.0 | 81 | -3.1pp | flat |
| 2026-07-02 13:47 | `gemma-4-e4b-it-q4-k-m` | 93.8% | 2.51 | 19.8 | 81 | -6.2pp | flat |
| 2026-07-02 13:36 | `gemma-4-e4b-it-q4-k-m` | 93.8% | 2.92 | 20.6 | 81 | -6.2pp | flat |
| 2026-07-02 13:26 | `gemma-4-e4b-it-q4-k-m` | 96.9% | 2.52 | 18.7 | 81 | -3.1pp | flat |
| 2026-07-02 13:15 | `gemma-4-e4b-it-q4-k-m` | 96.9% | 2.54 | 19.6 | 81 | -3.1pp | flat |
| 2026-07-02 13:04 | `gemma-4-e4b-it-q4-k-m` | 93.8% | 3.07 | 19.8 | 81 | -6.2pp | flat |
| 2026-07-02 11:43 | `gemma-4-e4b-it-q4-k-m` | 95.3% | 2.91 | 16.4 | 81 | -4.7pp | flat |
| 2026-07-02 11:15 | `gemma-4-e4b-it-q4-k-m` | 93.8% | 2.81 | 17.7 | 81 | -6.2pp | flat |
| 2026-07-02 00:39 | `gemma-4-e4b-it-q4-k-m` | 96.9% | 2.82 | 20.1 | 77 | -3.1pp | flat |
| 2026-07-02 00:13 | `gemma-4-e4b-it-q4-k-m` | 96.9% | 2.76 | 15.1 | 77 | -3.1pp | flat |
| 2026-07-01 22:24 | `gemma-4-26b-a4b-it-qat-q4-0` | 92.2% | 3.00 | 12.1 | 77 | -4.6pp | flat |
| 2026-07-01 21:58 | `gemma-4-e4b-it-q4-k-m` | 95.3% | 2.72 | 18.2 | 77 | -4.7pp | flat |
| 2026-07-01 19:30 | `gemma-4-e4b-it-q4-k-m` | 96.9% | 2.58 | 18.7 | 77 | -3.1pp | flat |
