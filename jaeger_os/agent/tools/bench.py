"""Agent-callable system benchmark.

  • run_benchmark(tags, limit, ids) — runs the flat bench corpus
    against the LIVE agent pipeline and returns a scored summary.

This is the bench the user invokes by saying "run the system
benchmark" to the agent. The agent calls this tool, which drives
every case back through the same boot/system-prompt/dispatch path the
user just talked to — the most honest signal we can get for "did
this change regress routing?"

Tier: WRITE_LOCAL — the bench writes per-run markdown + jsonl under
``<instance>/logs/bench/``. Without that gate a curious user could
poke at the bench and unknowingly trigger a multi-minute model
session; the confirm/tier system lets the user opt in deliberately.

**Permission gating during the bench.** Many bench cases call
WRITE_LOCAL tools (write_file, delete_file, schedule_prompt,
execute_code). Under a strict confirm provider, EACH of those calls
would prompt the user — which both ruins the bench latency numbers
and effectively breaks the bench when run non-interactively. We
solve this by installing a *bench scope* permission policy for the
duration of the inner run: WRITE_LOCAL is auto-approved (the user
already approved by saying "run the benchmark"); higher tiers
(EXTERNAL_EFFECT, HARDWARE, PRIVILEGED, DEV_BYPASS) still defer to
the outer provider, so a runaway case can't reach for the network /
shell / hardware without the user explicitly approving each one.
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any, Iterator

from ._common import _require_layout
from jaeger_os.core.safety.permissions import (
    ConfirmationProvider,
    PermissionPolicy,
    PermissionRequest,
    PermissionTier,
    current_policy,
    requires_tier,
    use_policy,
)


# Tiers the bench scope auto-approves on the user's behalf. Anything
# stricter than this still goes through the outer confirm provider —
# a recovery case that tries to ssh out, run a shell command, or
# poke at hardware still has to ask. The bench corpus deliberately
# stays inside the sandbox so this set is tight by design.
_BENCH_AUTO_APPROVED: frozenset[PermissionTier] = frozenset({
    PermissionTier.READ_ONLY,
    PermissionTier.WRITE_LOCAL,
})


class _BenchScopeProvider:
    """Confirmation provider that auto-approves bench-scoped tiers.

    Anything in :data:`_BENCH_AUTO_APPROVED` is approved without
    prompting. Anything stricter falls through to the wrapped
    "outer" provider — so the user still controls EXTERNAL_EFFECT
    (web posts, send_message), HARDWARE (computer_use, listen),
    PRIVILEGED, and DEV_BYPASS. The outer provider's "yes" / "no"
    decision wins for those tiers exactly as it would outside the
    bench."""

    def __init__(self, outer: ConfirmationProvider) -> None:
        self._outer = outer

    def confirm(self, request: PermissionRequest) -> bool:
        if request.tier in _BENCH_AUTO_APPROVED:
            return True
        return self._outer.confirm(request)


@contextlib.contextmanager
def _bench_permission_scope() -> Iterator[None]:
    """Install a bench-scoped confirmation provider for the duration
    of the ``with`` block. The outer provider is preserved as the
    fall-through for any tier the bench scope doesn't auto-approve."""
    outer_policy = current_policy()
    scoped_policy = PermissionPolicy(
        mode=outer_policy.mode,
        confirmation=_BenchScopeProvider(outer_policy.confirmation),
    )
    with use_policy(scoped_policy):
        yield


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="bench",
    operation="run_benchmark",
    summary="run the agent self-benchmark against the live pipeline",
)
def run_benchmark(
    tags: str = "",
    limit: int = 0,
    ids: str = "",
    save: bool = True,
    hermetic: bool = True,
) -> dict[str, Any]:
    """Run the flat self-benchmark suite against the live agent.

    Every case fires through the SAME pipeline you're using right
    now — same system prompt, same lean surface, same drift parser,
    same dispatch. That's what makes this trustworthy: a regression
    here is a regression in the surface the user actually talks to.

    Args:
      tags:  comma-separated subset of bench tags (e.g.
             ``"routing,memory"``). Empty = full corpus. Available
             tags: routing, multistep, multiturn, recovery, memory,
             files, web, code, audio, schedule.
      limit: cap on the number of cases (after tag filtering).
             0 = no cap. Multi-turn sessions are kept whole.
      ids:   comma-separated case ids to run (e.g.
             ``"time_now,calc_sqrt"``). Empty = no id filter.
      save:  when True (default), the per-row jsonl + a summary
             markdown are written under
             ``<instance>/logs/bench/<timestamp>/``.
      hermetic: when True (default), snapshots the live instance's
             mutable memory files (facts, board, schedules,
             episodic) before the run and restores them after, so
             bench writes don't pollute the user's state and
             prior state doesn't pollute the bench. Pass False to
             let bench writes persist (rarely useful).

    Returns a summary dict with topline counts plus per-tag breakdown
    and the failure list. Run individual rows by passing ``ids`` —
    handy for re-running a single flaky case after a fix.
    """
    from jaeger_os.core.bench import run_bench, summarise
    from jaeger_os.main import _pipeline

    client = _pipeline.get("client")
    if client is None:
        return {"ok": False, "error": "no live client — bench can only run "
                                       "inside a booted instance"}

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    id_list = [i.strip() for i in (ids or "").split(",") if i.strip()]
    cap = int(limit) if limit and int(limit) > 0 else None

    started = time.perf_counter()
    # Inside the scope: bench cases auto-approve sandboxed
    # WRITE_LOCAL operations (write_file, delete_file, etc.) so the
    # user isn't prompted for every single case. Higher tiers still
    # defer to the outer provider — a recovery case that tries to
    # reach the network or fire computer_use still has to ask.
    with _bench_permission_scope():
        rows = run_bench(client, tags=tag_list or None, ids=id_list or None,
                         limit=cap, hermetic=bool(hermetic))
    summary = summarise(rows)
    summary["wall_s"] = round(time.perf_counter() - started, 2)

    if save and rows:
        try:
            layout = _require_layout()
            # Stamp the model identity into the summary so the
            # history aggregator can attribute the run. Then nest the
            # output under ``<logs>/bench/<model>/<ts>/`` so a
            # "list every run of this model" browse is a single
            # ``ls``, not a parse-summary-jsons exercise.
            model_name = "unknown"
            try:
                from jaeger_os.main import _pipeline as _pl
                _cfg = _pl.get("config")
                _mp = getattr(getattr(_cfg, "model", None), "model_path", None)
                if _mp:
                    summary["model_path"] = str(_mp)
                    model_name = Path(str(_mp)).stem
                    summary["model_name"] = model_name
            except Exception:  # noqa: BLE001
                pass
            ts = time.strftime("%Y%m%d-%H%M%S")
            summary["run_id"] = ts
            out_dir = Path(layout.logs_dir) / "bench" / model_name / ts
            out_dir.mkdir(parents=True, exist_ok=True)
            # Match the flat-bench naming convention: every artifact
            # carries ``<model>-<ts>`` so a file copied out of its
            # folder still self-identifies. The generic
            # ``summary.json`` / ``rows.jsonl`` filenames the original
            # layout used were impossible to attribute once moved.
            prefix = f"{model_name}-{ts}"
            (out_dir / f"{prefix}-rows.jsonl").write_text(
                "\n".join(json.dumps(r, default=str, ensure_ascii=False)
                          for r in summary["rows"]) + "\n",
                encoding="utf-8",
            )
            (out_dir / f"{prefix}-summary.json").write_text(
                json.dumps(
                    {k: v for k, v in summary.items() if k != "rows"},
                    indent=2, default=str, ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (out_dir / f"{prefix}-summary.md").write_text(
                _render_markdown(summary), encoding="utf-8",
            )
            summary["report_dir"] = str(out_dir)
        except Exception as exc:  # noqa: BLE001 — never let bookkeeping
            # break the agent's view of the bench result
            summary["save_error"] = f"{type(exc).__name__}: {exc}"

    # Strip the rows from the agent-facing return — the full rows file
    # is on disk, and shoving 40 KB of jsonl into the model's context
    # is exactly what truncate_oversized_result would clip anyway.
    summary.pop("rows", None)
    return summary


def _render_markdown(summary: dict[str, Any]) -> str:
    """One-page summary suitable for ``logs/bench/<ts>/summary.md``."""
    total = summary.get("total", 0) or 1
    pass_pct = 100 * summary.get("passed", 0) / total
    metrics = summary.get("metrics") or {}
    lines = [
        "# Jaeger-OS — system benchmark",
        "",
        f"- **{summary.get('passed', 0)} / {summary.get('total', 0)}** "
        f"cases passed ({pass_pct:.0f}%)",
        f"- routing: {summary.get('routing_passed', 0)} / "
        f"{summary.get('routing_total', 0)}",
        f"- answer-checks: {summary.get('answer_passed', 0)} / "
        f"{summary.get('answer_total', 0)}",
        f"- errors: {summary.get('errors', 0)}",
        f"- elapsed: {summary.get('elapsed_s', 0)}s "
        f"(wall: {summary.get('wall_s', 0)}s)",
        "",
        "## Performance metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| avg latency / case | {metrics.get('avg_latency_s', 0):.2f}s |",
        f"| p50 latency | {metrics.get('p50_latency_s', 0):.2f}s |",
        f"| p95 latency | {metrics.get('p95_latency_s', 0):.2f}s |",
        f"| min / max latency | {metrics.get('min_latency_s', 0):.2f}s / "
        f"{metrics.get('max_latency_s', 0):.2f}s |",
        f"| tool dispatches (total) | {metrics.get('total_tool_dispatches', 0)} |",
        f"| avg tools / turn | {metrics.get('avg_tools_per_turn', 0):.2f} |",
        f"| answer tokens (total) | {metrics.get('answer_tokens_total', 0)} |",
        f"| answer tokens / case (avg) | {metrics.get('answer_tokens_avg', 0):.1f} |",
        f"| answer tokens / sec (corpus) | {metrics.get('answer_tokens_per_sec', 0):.1f} |",
        f"| prompt tokens (total) | {metrics.get('prompt_tokens_total', 0)} |",
        f"| dispatch errors | {metrics.get('cases_with_errors', 0)} |",
        "",
        f"_Token source: **{metrics.get('answer_tokens_source', 'whitespace_estimate')}**. "
        f"{metrics.get('tokens_note', '')}_",
        "",
        "## By suite (graded against advisory thresholds)",
        "",
        "| Suite | Passed | Total | Rate | Threshold | OK | Avg s | p95 s |",
        "|---|---:|---:|---:|---:|:---:|---:|---:|",
    ]
    # Suites are the operator-facing roll-up — "routing 22/25" reads
    # straight; "routing 88% (threshold 85% ✓)" tells them whether to
    # cut a release without staring at the per-case table. Per-suite
    # avg + p95 timing exposes a regression that slows a category
    # without changing its pass rate.
    suites = summary.get("suites") or {}
    for name, s in suites.items():
        rate_pct = 100 * s.get("pass_rate", 0.0)
        thresh_pct = 100 * s.get("threshold", 0.0)
        ok = "✓" if s.get("meets_threshold") else "✗"
        lines.append(
            f"| {name} | {s.get('passed', 0)} | {s.get('total', 0)} | "
            f"{rate_pct:.0f}% | {thresh_pct:.0f}% | {ok} | "
            f"{s.get('avg_latency_s', 0):.2f} | "
            f"{s.get('p95_latency_s', 0):.2f} |"
        )
    lines.append("")
    lines.append("## By tag (every tag the corpus uses)")
    lines.append("")
    lines.append("| Tag | Passed | Total | Avg s |")
    lines.append("|---|---:|---:|---:|")
    for tag, counts in sorted((summary.get("by_tag") or {}).items()):
        lines.append(
            f"| {tag} | {counts.get('passed', 0)} | "
            f"{counts.get('total', 0)} | "
            f"{counts.get('avg_latency_s', 0):.2f} |"
        )
    failures = summary.get("failures") or []
    if failures:
        lines.append("")
        lines.append(f"## Failures ({len(failures)})")
        lines.append("")
        for f in failures:
            lines.append(f"### {f['id']}")
            lines.append(f"- prompt: {f['prompt']!r}")
            lines.append(f"- tools called: {f['tools_called']}")
            lines.append(f"- routing_ok: {f['routing_ok']}, "
                         f"answer_ok: {f['answer_ok']}, "
                         f"no_hallucination: {f['no_hallucination']}")
            if f.get("error"):
                lines.append(f"- error: {f['error']}")
            lines.append("")
    return "\n".join(lines) + "\n"


__all__ = ["run_benchmark"]
