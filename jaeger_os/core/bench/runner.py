"""Flat bench runner — drives every case through the live agent loop.

The bench runs IN-PROCESS against the same model the agent is currently
using. That means:

  * the system prompt the model sees is the real one
  * the lean surface is the real one
  * the drift parser, dispatch, tier checks all fire
  * answers come back through the real finalizer

Re-entrancy note: this module is called FROM a tool dispatch inside
``drive_one_turn``. The outer turn acquired ``_pipeline['llm_lock']``,
but ``drive_one_turn`` itself doesn't re-acquire — it just calls the
adapter, which calls the model. Each bench case builds a FRESH
``JaegerAgent`` against the same client (separate message history,
shared LLM), so there's no nested lock contention.

Multi-turn handling: cases sharing a ``session`` key reuse the same
``JaegerAgent`` instance, so the prior turn's tool calls + answer
are in history when the next turn fires — same as a real
conversation. Cases without a ``session`` key get a unique session
per case (single-turn purity).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tempfile
import time
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .cases import BenchCase, CASES, UMBRELLA_EQUIVALENTS


@dataclass
class BenchRow:
    """One bench case's result. Mirrors the legacy TurnRow shape for
    the per-case fields, but the pass/fail booleans are pre-computed
    so the renderer is a dumb projection."""

    id: str
    prompt: str
    tags: list[str]
    tools_called: list[str]
    answer: str
    elapsed_s: float
    routing_ok: bool | None      # None ⇒ no expected_tools to check
    ordered_ok: bool | None      # None ⇒ ordered=False
    answer_ok: bool | None       # None ⇒ no answer_contains_* set
    no_hallucination: bool       # True when none of hallucination_signals fired
    clean_output: bool           # True when the visible answer carries no tool/think markup
    safety_ok: bool | None       # None ⇒ no forbidden_tools to check
    error: str | None
    case_pass: bool              # rolls up every applicable check
    # Real token counts when the adapter reported ``usage`` on its
    # raw response (llama-cpp / OpenAI / Anthropic). 0 means "adapter
    # didn't tell us" — the summary falls back to a whitespace-split
    # estimate in that case.
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Loop-health telemetry (v1.2) — straight from the turn result so
    # every bench run systematically measures the agent loop, not just
    # the answers. ``ttft_s`` is the REAL time-to-first-token of the
    # turn's first model call (None when the adapter couldn't report
    # one); ``halt_reason`` is non-None when a backstop/interrupt cut
    # the turn short; ``iterations`` is the loop's step count;
    # ``skipped_final`` marks the fast skip-final path.
    ttft_s: float | None = None
    halt_reason: str | None = None
    iterations: int = 0
    skipped_final: bool = False
    # Skill selection (the 'skill' category): which playbooks the agent
    # pulled via skill(view), and whether it selected the ones the case
    # expected. ``skill_ok`` is None when the case sets no expected_skills.
    skills_viewed: list[str] = field(default_factory=list)
    skill_ok: bool | None = None


# ── Helpers ─────────────────────────────────────────────────────────


def _matches_tool_set(observed: list[str], expected: list[str],
                      *, ordered: bool) -> bool:
    """Set-match (or ordered subsequence) with umbrella-tool tolerance.

    Umbrella tolerance: a corpus expecting ``remember`` accepts a model
    that called ``memory`` (the umbrella). Without this we'd punish the
    model for routing correctly to the consolidated tool — the corpus
    intentionally uses the pre-consolidation names so historical
    baselines stay comparable."""
    if not expected:
        return True
    def _hit(name: str, observed: list[str]) -> bool:
        if name in observed:
            return True
        return any(eq in observed for eq in UMBRELLA_EQUIVALENTS.get(name, set()))
    if not ordered:
        return all(_hit(name, observed) for name in expected)
    # Ordered: observed must contain expected as a subsequence (umbrella
    # equivalents count as a match for that step).
    expected_iter = iter(expected)
    want = next(expected_iter, None)
    if want is None:
        return True
    for tool in observed:
        equivalents = {want} | UMBRELLA_EQUIVALENTS.get(want, set())
        if tool in equivalents:
            want = next(expected_iter, None)
            if want is None:
                return True
    return False


# Digit-group separators: a model may write "9,999" where a check wants "9999".
# Strip commas that sit BETWEEN digits so the numeric answer still matches.
_THOUSANDS_SEP = re.compile(r"(?<=\d),(?=\d)")


def _contains_any(haystack: str, needles: list[str]) -> bool:
    if not needles:
        return True
    lower = (haystack or "").lower()
    normalized = _THOUSANDS_SEP.sub("", lower)
    return any(n.lower() in lower or n.lower() in normalized for n in needles)


def _contains_all(haystack: str, needles: list[str]) -> bool:
    if not needles:
        return True
    lower = (haystack or "").lower()
    return all(n.lower() in lower for n in needles)


# ── Live-pipeline turn driver ──────────────────────────────────────


def _drive_one(
    client: Any, prompt: str, *,
    agent_cache: dict[str, Any],
    session_key: str,
) -> tuple[list[str], str, float, str | None, int, int, dict[str, Any]]:
    """Run one turn through a session-bound :class:`JaegerAgent`. Returns
    ``(tools_called, answer, elapsed_s, error, prompt_tokens,
    completion_tokens, loop_meta)`` — ``loop_meta`` carries the turn's
    loop-health telemetry (ttft_s / halt_reason / iterations / skipped).

    Token counts come from the adapter's ``usage`` field — real
    tokenizer counts on llama-cpp / OpenAI / Anthropic. Adapters that
    don't expose usage contribute zero; the summary then falls back
    to a whitespace-split estimate."""
    from jaeger_os.agent.loop.runtime_bridge import (
        build_jaeger_agent, drive_one_turn,
    )
    from jaeger_os.main import SKIP_FINAL_TOOLS, _get_agent, _pipeline

    if session_key not in agent_cache:
        _get_agent(client)  # mirror tools onto the registry
        _cfg = _pipeline.get("config")
        _ctx = getattr(getattr(_cfg, "model", None), "ctx", None)
        _layout = _pipeline.get("layout")
        _artifact_dir = (
            (_layout.logs_dir / "tool_results") if _layout is not None else None
        )
        # Bench-scoped stall-timeout override. ``JAEGER_BENCH_STALL_S``
        # lets a sweep fail stuck cases FAST (e.g. 45s) so a model that
        # stalls on many cases doesn't blow the per-model wall-clock cap
        # and time out with zero data. Reasoning models still get their
        # 300s floor (LocalLlamaAdapter bumps it). Falls back to the
        # config's ``model.stall_timeout_s``, then the backend default.
        _stall_env = os.environ.get("JAEGER_BENCH_STALL_S", "").strip()
        if _stall_env:
            try:
                _stall_s: float | None = float(_stall_env)
            except ValueError:
                _stall_s = None
        else:
            _stall_s = getattr(getattr(_cfg, "model", None),
                               "stall_timeout_s", None)
        agent_cache[session_key] = build_jaeger_agent(
            client,
            system_prompt=_pipeline.get("system_prompt", ""),
            toolsets=_pipeline.get("toolsets"),
            skip_final_tools=SKIP_FINAL_TOOLS,
            ctx_window=_ctx,
            artifact_dir=_artifact_dir,
            stale_call_timeout_s=_stall_s,
        )
    jaeger_agent = agent_cache[session_key]

    started = time.perf_counter()
    error: str | None = None
    out: dict[str, Any] = {}
    try:
        # Devnull-redirect so the bench's nested turns don't spam the
        # live agent's stdout. The model's own progress is captured in
        # the returned dict.
        with open(os.devnull, "w") as devnull, redirect_stdout(devnull):
            out = drive_one_turn(jaeger_agent, prompt)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started

    tools: list[str] = []
    skills_viewed: list[str] = []
    for msg in (out.get("new_messages") or []):
        if msg.get("role") != "assistant":
            continue
        for tc in (msg.get("tool_calls") or []):
            name = tc.get("name") or ""
            if name:
                tools.append(name)
            # Skill selection: a skill(view/use, name=...) call is the
            # agent choosing a specific playbook. Capture WHICH one so
            # the 'skill' category can assert it picked the right skill,
            # not just that it researched. (Tool names alone can't tell
            # skill('ascii-art') from skill('arxiv').) Applies to playbook
            # AND tool-skills — skill-first means both get viewed before use.
            if name in ("list_skills", "use_skill"):
                args = tc.get("arguments") or {}
                # Adapters may hand arguments back as a JSON string rather
                # than a dict — parse so a skill call is NEVER missed
                # (flag skill use as reliably as a tool call).
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (ValueError, TypeError):
                        args = {}
                if not isinstance(args, dict):
                    args = {}
                # use_skill(name=…) is a direct enum selection; skill(view,
                # name=…) is the meta-tool form. Both = viewing a playbook.
                if name == "use_skill" or str(args.get("action") or "").lower() in (
                        "view", "use", "read", "get", "open"):
                    target = str(args.get("name") or args.get("query") or "").strip()
                    if target:
                        skills_viewed.append(target)

    answer = out.get("answer", "") or ""
    prompt_tokens = int(out.get("prompt_tokens") or 0)
    completion_tokens = int(out.get("completion_tokens") or 0)
    meta: dict[str, Any] = {
        "ttft_s": out.get("ttft_s"),
        "halt_reason": out.get("halt_reason"),
        "iterations": int(out.get("iterations") or 0),
        "skipped_final": bool(out.get("skipped", False)),
        "skills_viewed": skills_viewed,
    }
    return tools, answer, elapsed, error, prompt_tokens, completion_tokens, meta


# ── Scoring ─────────────────────────────────────────────────────────


# Markup that must NEVER reach the user-visible answer. A leak here is
# the "grader-happy, user-garbage" class of bug: the right tool fired and
# the expected substring is present (so routing_ok + answer_ok pass), but
# raw tool-call / reasoning markup bled into what the user actually sees.
# The gemma-4 ``<|tool_call>call:speak{text:<|"|>…<|"|>}`` envelope leak
# (2026-06-20) sailed through every check until this gate existed. These
# tokens are unambiguous markup — natural-language answers never contain
# ``<|tool_call`` or ``<|"|>`` — so the check is safe to apply to EVERY
# case, not opt-in.
_VISIBLE_MARKUP_MARKERS: tuple[str, ...] = (
    "<|tool_call", "<tool_call>", "</tool_call>", "<|/tool_call",
    "<|channel", "<channel|>", "<|message", "<|python_tag",
    "<|im_start", "<|im_end",
    '<|"|>',                 # gemma's inner quote marker
    "[TOOL_CALLS]",          # mistral envelope
    "<think>", "</think>",   # reasoning that should have been stripped
)


def _visible_output_clean(answer: str) -> bool:
    """True when the finalised answer carries no tool-call / reasoning
    markup — the user-visible-output contract every case must honour."""
    if not answer:
        return True
    return not any(m in answer for m in _VISIBLE_MARKUP_MARKERS)


def _score(case: BenchCase, tools: list[str], answer: str,
           error: str | None, elapsed_s: float,
           skills_viewed: list[str] | None = None) -> BenchRow:
    """Apply each of the case's optional checks; roll up to ``case_pass``."""
    skills_viewed = skills_viewed or []
    routing_ok: bool | None = None
    ordered_ok: bool | None = None
    if case.expected_tools:
        routing_ok = _matches_tool_set(tools, case.expected_tools, ordered=False)
        if case.ordered:
            ordered_ok = _matches_tool_set(tools, case.expected_tools, ordered=True)

    # Skill selection ('skill' category): every expected skill must have
    # been viewed. Substring-tolerant so a case can say 'ascii-art' and
    # match a viewed 'ascii-art' regardless of category prefixing.
    skill_ok: bool | None = None
    if case.expected_skills:
        viewed_l = [s.lower() for s in skills_viewed]
        skill_ok = all(
            any(want.lower() in v or v in want.lower() for v in viewed_l)
            for want in case.expected_skills
        )

    answer_ok: bool | None = None
    if case.answer_contains_any or case.answer_contains_all:
        any_ok = _contains_any(answer, case.answer_contains_any) \
            if case.answer_contains_any else True
        all_ok = _contains_all(answer, case.answer_contains_all) \
            if case.answer_contains_all else True
        answer_ok = bool(any_ok and all_ok)

    lower = (answer or "").lower()
    no_hallucination = not any(
        s.lower() in lower for s in case.hallucination_signals
    )

    # Mandatory visible-output contract — applies to every case.
    clean_output = _visible_output_clean(answer)

    # Safety gate: a case that lists ``forbidden_tools`` must NOT see any
    # of them dispatched (the destructive command must be refused, not
    # executed). Umbrella-tool equivalents count as a hit — the dict
    # maps fine-grained name → set of umbrella names it acts as, so we
    # expand the CALLED tools forward and check whether any reaches a
    # forbidden one. ``None`` for cases without a safety check so the
    # renderer can tell "no check" apart from "checked and passed".
    safety_ok: bool | None = None
    if case.forbidden_tools:
        forbidden: set[str] = set(case.forbidden_tools)
        def _hits_forbidden(called: str) -> bool:
            if called in forbidden:
                return True
            return any(eq in forbidden
                       for eq in UMBRELLA_EQUIVALENTS.get(called, set()))
        safety_ok = not any(_hits_forbidden(t) for t in tools)

    pieces: list[bool] = [no_hallucination, clean_output, error is None]
    if routing_ok is not None:
        pieces.append(routing_ok)
    if ordered_ok is not None:
        pieces.append(ordered_ok)
    if skill_ok is not None:
        pieces.append(skill_ok)
    if answer_ok is not None:
        pieces.append(answer_ok)
    if safety_ok is not None:
        pieces.append(safety_ok)
    case_pass = all(pieces)

    return BenchRow(
        id=case.id, prompt=case.prompt, tags=list(case.tags),
        tools_called=tools, answer=answer, elapsed_s=round(elapsed_s, 3),
        routing_ok=routing_ok, ordered_ok=ordered_ok, answer_ok=answer_ok,
        no_hallucination=no_hallucination, clean_output=clean_output,
        safety_ok=safety_ok, error=error, case_pass=case_pass,
        skills_viewed=list(skills_viewed), skill_ok=skill_ok,
    )


# ── Filtering / running ─────────────────────────────────────────────


def _loop_health_metrics(rows: list[BenchRow]) -> dict[str, Any]:
    """Aggregate the v1.2 loop-health fields across a run."""
    ttfts = sorted(r.ttft_s for r in rows if r.ttft_s)
    halt_reasons: dict[str, int] = {}
    for r in rows:
        if r.halt_reason:
            # Group parameterised reasons ("hit max_iterations=24 …")
            # by their first word so the histogram stays readable.
            key = str(r.halt_reason).split("=")[0].strip()[:60]
            halt_reasons[key] = halt_reasons.get(key, 0) + 1
    iters = [r.iterations for r in rows if r.iterations > 0]
    out: dict[str, Any] = {
        "halt_reasons": halt_reasons,
        "halted_turns": sum(halt_reasons.values()),
        "avg_iterations": round(sum(iters) / len(iters), 2) if iters else 0.0,
        "skip_final_turns": sum(1 for r in rows if r.skipped_final),
    }
    if ttfts:
        out["ttft_avg_s"] = round(sum(ttfts) / len(ttfts), 3)
        out["ttft_p50_s"] = round(_percentile(ttfts, 50), 3)
        out["ttft_p95_s"] = round(_percentile(ttfts, 95), 3)
        out["ttft_reported"] = len(ttfts)
    else:
        out["ttft_reported"] = 0
    return out


def _filter_cases(cases: list[BenchCase], *,
                  tags: list[str] | None,
                  ids: list[str] | None,
                  limit: int | None) -> list[BenchCase]:
    """Filter the corpus down to what the caller asked for. Multi-turn
    sessions are kept WHOLE — if any of a session's rows match the
    filter, every row in that session is included (otherwise turn 2
    would fail because turn 1's history is gone)."""
    sel = list(cases)
    if tags:
        wanted = {t.lower() for t in tags}
        sel = [c for c in sel if wanted.intersection({t.lower() for t in c.tags})]
    if ids:
        sel = [c for c in sel if c.id in set(ids)]
    if sel and sel != cases:
        # Re-include any rows that share a session with a selected row
        # but didn't themselves match the filter.
        selected_sessions = {c.session for c in sel if c.session}
        if selected_sessions:
            for c in cases:
                if c.session in selected_sessions and c not in sel:
                    sel.append(c)
            # Preserve original corpus order so multi-turn rows stay
            # in turn order.
            order = {id(c): i for i, c in enumerate(cases)}
            sel.sort(key=lambda c: order.get(id(c), 1 << 30))
    if limit is not None and limit > 0:
        sel = sel[:limit]
    return sel


# ── Hermetic mode — snapshot + restore mutable instance state ──────


# Files the bench writes to: facts.json (memory verbs), board.json
# (kanban / deepthink), schedules.json (cron), episodic.jsonl
# (every turn append). Snapshotting these around a run gives us
# 90% of the value of a full tmp-instance hermetic mode at 5% of
# the complexity: the user's live memory is untouched.
_MUTABLE_MEMORY_FILES: tuple[str, ...] = (
    "facts.json",
    "board.json",
    "schedules.json",
    "episodic.jsonl",
    # The REAL memory backend is SQLite (facts.json/episodic.jsonl are the
    # legacy files, lazy-migrated in). Without snapshotting the .db (+ its
    # WAL sidecars) the bench's writes leaked into the operator's live memory
    # and NEVER rolled back — that baked stale "favorite color" facts into
    # state.db and broke corpus B's recall cases (they read the pollution,
    # not the store). 2026-07-03.
    "state.db", "state.db-wal", "state.db-shm",
    "sessions.db", "sessions.db-wal", "sessions.db-shm",
)


def _checkpoint_sqlite() -> None:
    """Fold the state.db WAL into the main db file so a plain file copy
    of ``state.db`` is a complete, consistent snapshot. Best-effort."""
    with contextlib.suppress(Exception):
        from jaeger_os.core.memory import sqlite_store
        if sqlite_store.is_bound():
            sqlite_store.connection().execute(
                "PRAGMA wal_checkpoint(TRUNCATE)")


def _close_sqlite_stores() -> bool:
    """Close the process's live SQLite connections (state.db singleton +
    the sessions.db store) so the on-disk files can be safely replaced.
    Returns True when something was closed (caller should re-bind)."""
    closed = False
    with contextlib.suppress(Exception):
        from jaeger_os.core.memory import sqlite_store
        if sqlite_store.is_bound():
            sqlite_store.close()
            closed = True
    with contextlib.suppress(Exception):
        from jaeger_os.core import sessions
        sessions.reset_for_tests()   # closes + clears the lazy singleton
    return closed


def _rebind_sqlite_stores(layout: Any) -> None:
    """Reopen the memory store against the (restored) files. The sessions
    store reopens lazily on its next ``get_store`` call."""
    with contextlib.suppress(Exception):
        from jaeger_os.core.memory import memory as _memory_mod
        _memory_mod.bind(layout)


@contextlib.contextmanager
def _hermetic_memory(layout: Any) -> Iterator[None]:
    """Snapshot the mutable memory files on entry; restore them on
    exit. Any bench-driven writes between are invisible to the user's
    live state after the ``with`` block.

    SQLite handling (the part that bit us): a WAL database CANNOT be
    safely copied or replaced under an open connection — the page cache
    and mmap'd -shm index would disagree with disk, corrupting the file
    or resurrecting bench rows. So we ``wal_checkpoint(TRUNCATE)`` before
    the snapshot (making the bare .db a complete copy), and on restore we
    CLOSE the live connections first, swap the files, then re-bind.

    Best-effort throughout — if a snapshot or restore fails (no
    permission, disk full, etc.) we log and let the run continue.
    The alternative — refusing to run the bench because we can't
    guarantee perfect isolation — would be worse for the operator
    who just wants the routing number.

    Layout duck-type: anything with a ``memory_dir`` attribute that
    points at a real directory works. Tests can pass a tmp-path
    ``SimpleNamespace``."""
    memory_dir = Path(getattr(layout, "memory_dir", "") or "")
    if not memory_dir or not memory_dir.is_dir():
        # No layout / no memory dir → run un-snapshotted. The bench
        # cases that don't touch persistent state still work fine.
        yield
        return

    _checkpoint_sqlite()
    snapshot_dir = Path(tempfile.mkdtemp(prefix=".bench_snapshot_",
                                         dir=str(memory_dir)))
    saved: dict[str, Path] = {}
    try:
        for name in _MUTABLE_MEMORY_FILES:
            src = memory_dir / name
            if src.is_file():
                dst = snapshot_dir / name
                try:
                    shutil.copy2(src, dst)
                    saved[name] = dst
                except OSError:
                    # Couldn't snapshot this one — log mentally,
                    # carry on. The post-restore step will skip it.
                    pass
        yield
    finally:
        # Close the live SQLite connections BEFORE touching their files —
        # restoring under an open connection is undefined behaviour.
        rebind = _close_sqlite_stores()
        # Restore: copy each snapshotted file back. If snapshot was
        # missing (file didn't exist pre-run) AND the bench created
        # it, remove the bench-created file so the live state stays
        # at "absent".
        for name in _MUTABLE_MEMORY_FILES:
            live = memory_dir / name
            backup = saved.get(name)
            if backup is not None and backup.is_file():
                try:
                    shutil.copy2(backup, live)
                except OSError:
                    pass
            elif live.is_file():
                # File didn't exist pre-bench; the bench created it.
                # Remove so the user's instance returns to its
                # pre-bench shape exactly.
                try:
                    live.unlink()
                except OSError:
                    pass
        if rebind:
            _rebind_sqlite_stores(layout)
        try:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
        except OSError:
            pass


def run_bench(
    client: Any,
    *,
    cases: list[BenchCase] | None = None,
    tags: list[str] | None = None,
    ids: list[str] | None = None,
    limit: int | None = None,
    progress: Any = None,
    hermetic: bool = True,
) -> list[BenchRow]:
    """Run the flat bench against ``client`` and return one
    :class:`BenchRow` per case.

    ``progress`` (optional callable) is invoked as
    ``progress(idx, total, case_id, passed, elapsed_s)`` after every
    case — useful for surfacing live progress in the tool result or
    on the TUI status line.

    ``hermetic=True`` (default) snapshots the live instance's
    mutable memory files (``facts.json`` / ``board.json`` /
    ``schedules.json`` / ``episodic.jsonl``) before the run and
    restores them after. This kills the contamination that made
    ``creds_list`` / ``schedule_list`` style cases fail against an
    instance with prior state — the bench reads "what does it
    look like RIGHT NOW with no bleed from earlier sessions" and
    the operator's live memory is untouched after the run finishes.
    Pass ``hermetic=False`` for legacy behaviour (bench writes
    persist; rarely useful)."""
    corpus = cases if cases is not None else CASES
    selected = _filter_cases(corpus, tags=tags, ids=ids, limit=limit)
    rows: list[BenchRow] = []
    agent_cache: dict[str, Any] = {}
    cleanup_queue: list[tuple[str, str]] = []  # (session, prompt)

    # Look up the live layout for the hermetic snapshot. If the
    # client wasn't booted via the standard pipeline (raw test
    # fixture, etc.) we just run un-snapshotted.
    snapshot_ctx: contextlib.AbstractContextManager[Any] = contextlib.nullcontext()
    if hermetic:
        try:
            from jaeger_os.main import _pipeline
            layout = _pipeline.get("layout")
            if layout is not None:
                snapshot_ctx = _hermetic_memory(layout)
        except Exception:  # noqa: BLE001 — snapshot is opt-in convenience
            pass

    # Tag every fact the bench writes as source='benchmark' so it never
    # masquerades as the operator's (and is trivially purgeable). Belt-and-
    # suspenders with the hermetic snapshot, which rolls the writes back.
    try:
        from jaeger_os.core.memory import memory as _mem
        _prev_source = _mem.set_memory_source("benchmark")
    except Exception:  # noqa: BLE001
        _mem = None
        _prev_source = None

    @contextlib.contextmanager
    def _memory_source_guard(mod: Any, prev: str | None) -> Iterator[None]:
        """Restore the live process's memory source EVEN IF the run raises —
        leaking source='benchmark' would silently mis-tag the operator's
        subsequent remembers and hide their real facts from recall."""
        try:
            yield
        finally:
            if mod is not None and prev is not None:
                with contextlib.suppress(Exception):
                    mod.set_memory_source(prev)

    @contextlib.contextmanager
    def _neutral_identity_guard() -> Iterator[None]:
        """Bench turns run under a NEUTRAL identity: the plain identity.yaml
        name, never the active character's. The bench measures the engine,
        not the costume — a character name in the worker prompt tints
        free-text answers (free_text_story wrote its story about HAL 9000)
        and answer_contains checks false-negative on the styled output.

        The prompt fragment reads ``JAEGER_BENCH_NEUTRAL_IDENTITY``; the
        pipeline's system prompt was assembled at boot, so it is rebuilt
        here under the flag and restored after — same try/finally shape as
        the memory-source guard above. Live behavior is untouched."""
        prev_env = os.environ.get("JAEGER_BENCH_NEUTRAL_IDENTITY")
        os.environ["JAEGER_BENCH_NEUTRAL_IDENTITY"] = "1"
        prev_prompt: str | None = None
        pipeline: Any = None
        try:
            from jaeger_os.agent.prompts.prompts import build_system_prompt
            from jaeger_os.main import _pipeline
            layout = _pipeline.get("layout")
            if layout is not None:
                prev_prompt = _pipeline.get("system_prompt")
                _pipeline["system_prompt"] = build_system_prompt(layout)
                pipeline = _pipeline
        except Exception:  # noqa: BLE001 — raw fixtures have no pipeline
            pass
        try:
            yield
        finally:
            if prev_env is None:
                os.environ.pop("JAEGER_BENCH_NEUTRAL_IDENTITY", None)
            else:
                os.environ["JAEGER_BENCH_NEUTRAL_IDENTITY"] = prev_env
            if pipeline is not None and prev_prompt is not None:
                with contextlib.suppress(Exception):
                    pipeline["system_prompt"] = prev_prompt

    with snapshot_ctx, _memory_source_guard(_mem, _prev_source), \
            _neutral_identity_guard():
        for idx, case in enumerate(selected):
            session_key = case.session or f"bench_{case.id}"
            tools, answer, elapsed, error, ptok, ctok, meta = _drive_one(
                client, case.prompt,
                agent_cache=agent_cache, session_key=session_key,
            )
            row = _score(case, tools, answer, error, elapsed,
                         skills_viewed=meta.get("skills_viewed") or [])
            row.prompt_tokens = ptok
            row.completion_tokens = ctok
            ttft = meta.get("ttft_s")
            row.ttft_s = round(float(ttft), 3) if ttft else None
            row.halt_reason = meta.get("halt_reason")
            row.iterations = int(meta.get("iterations") or 0)
            row.skipped_final = bool(meta.get("skipped_final", False))
            rows.append(row)
            for cleanup_prompt in (case.cleanup_after or []):
                cleanup_queue.append((f"{session_key}_cleanup", cleanup_prompt))
            if callable(progress):
                try:
                    progress(idx, len(selected), case.id, row.case_pass,
                             row.elapsed_s)
                except Exception:  # noqa: BLE001 — progress hook never breaks bench
                    pass

        # Best-effort cleanup of any state cases left behind. Failures
        # are ignored — the next run will overwrite anyway.
        for session_key, cleanup_prompt in cleanup_queue:
            try:
                _drive_one(client, cleanup_prompt,
                           agent_cache=agent_cache, session_key=session_key)
            except Exception:  # noqa: BLE001
                pass
    return rows


# ── Summarising ────────────────────────────────────────────────────


# Named suites the bench rolls up against. Each suite is a tag-filter
# over the corpus plus a pass-rate threshold the report grades against.
# Reporting in suites (rather than just topline) keeps regressions
# legible: "routing 22/25, multistep 7/9, recovery 5/9" tells the
# operator which category dropped — a flat "44/57" hides it.
#
# Thresholds are advisory — the bench still reports the raw pass count.
# Tune them per-model in a follow-up once we have data; current values
# are conservative ballparks based on the gemma-4-E4B baseline.
SUITES: dict[str, dict[str, Any]] = {
    "smoke":     {"tags": {"routing"}, "limit": 5,  "threshold": 0.80,
                  "blurb": "5-case sanity check; routing only"},
    "routing":   {"tags": {"routing"},          "threshold": 0.85,
                  "blurb": "single-turn, single-tool dispatch"},
    "multistep": {"tags": {"multistep"},        "threshold": 0.65,
                  "blurb": "single-turn, multiple-tool chaining"},
    "multiturn": {"tags": {"multiturn"},        "threshold": 0.70,
                  "blurb": "multi-turn conversations with carried history"},
    "recovery":  {"tags": {"recovery"},         "threshold": 0.60,
                  "blurb": "failure surface + anti-hallucination"},
    "full":      {"tags": None,                 "threshold": 0.70,
                  "blurb": "every case in the corpus"},
}


def _suite_rows(rows: list[BenchRow], suite_name: str) -> list[BenchRow]:
    """Filter ``rows`` to the cases that belong to ``suite_name``. The
    ``smoke`` suite additionally clips to ``limit`` cases so the
    summary stays honest about what was actually exercised."""
    spec = SUITES.get(suite_name)
    if spec is None:
        return []
    tags = spec.get("tags")
    if tags is None:
        out = list(rows)
    else:
        out = [r for r in rows if tags.intersection(r.tags)]
    limit = spec.get("limit")
    if limit:
        out = out[:int(limit)]
    return out


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile — fine for bench-row counts (~50)."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(pct / 100.0 * (len(s) - 1)))))
    return float(s[idx])


def _answer_tokens_estimate(answer: str) -> int:
    """Whitespace-split token count. Not a tokenizer — but for relative
    throughput comparisons across runs / models / sessions, the
    proportionality holds. Real token counts require adapter
    instrumentation (deferred — see adapters/base.py)."""
    if not answer:
        return 0
    return len(answer.split())


def summarise(rows: list[BenchRow]) -> dict[str, Any]:
    """Reduce a list of bench rows into a single dict the agent (or a
    rendering layer) can format. Keeps individual rows under ``rows``
    for drill-down while exposing topline counts, a per-suite
    breakdown, AND a metrics block (throughput, latency percentiles,
    tool-dispatch counts) — a flat "97% pass rate" hides which
    category regressed and a "92% in 311s" hides whether the model
    was slow per-turn or there were just many turns.

    Metrics block fields (all averages/percentiles in seconds; token
    counts are whitespace-split estimates, not real tokenizer counts):

      * ``avg_latency_s`` / ``p50_latency_s`` / ``p95_latency_s`` /
        ``min_latency_s`` / ``max_latency_s`` — per-case wall.
      * ``avg_tools_per_turn`` / ``total_tool_dispatches`` — routing
        cost across the corpus.
      * ``answer_tokens_total`` / ``answer_tokens_avg`` —
        whitespace-tokenised answer size.
      * ``answer_tokens_per_sec`` — corpus-wide output rate
        (sum-tokens / sum-elapsed). Useful for cross-model comparison
        even though the per-row number includes tool-dispatch time.
      * ``cases_with_errors`` — count of rows whose dispatch raised.
    """
    total = len(rows)
    passed = sum(1 for r in rows if r.case_pass)
    routing_checked = [r for r in rows if r.routing_ok is not None]
    answer_checked = [r for r in rows if r.answer_ok is not None]
    errors = sum(1 for r in rows if r.error)
    total_elapsed = sum(r.elapsed_s for r in rows)

    # Latency distribution.
    latencies = [r.elapsed_s for r in rows]
    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    min_lat = min(latencies) if latencies else 0.0
    max_lat = max(latencies) if latencies else 0.0

    # Tool dispatch.
    total_tools = sum(len(r.tools_called) for r in rows)
    avg_tools = (total_tools / total) if total else 0.0

    # Throughput. Prefer REAL tokens (adapter ``usage`` field) when
    # any row reported them; fall back to a whitespace-split estimate
    # on rows where the adapter didn't expose usage. The choice is
    # surfaced via ``answer_tokens_source`` so the report can label
    # the column honestly.
    real_completion_tokens = sum(r.completion_tokens for r in rows)
    real_prompt_tokens = sum(r.prompt_tokens for r in rows)
    if real_completion_tokens > 0:
        total_answer_tokens = real_completion_tokens
        tokens_source = "tokenizer"
    else:
        total_answer_tokens = sum(_answer_tokens_estimate(r.answer) for r in rows)
        tokens_source = "whitespace_estimate"
    avg_answer_tokens = (total_answer_tokens / total) if total else 0.0
    tokens_per_sec = (
        (total_answer_tokens / total_elapsed) if total_elapsed > 0 else 0.0
    )

    by_tag: dict[str, dict[str, Any]] = {}
    for r in rows:
        for tag in r.tags:
            slot = by_tag.setdefault(
                tag, {"total": 0, "passed": 0, "_elapsed_sum": 0.0},
            )
            slot["total"] += 1
            slot["_elapsed_sum"] += r.elapsed_s
            if r.case_pass:
                slot["passed"] += 1
    # Bake per-tag avg latency in and drop the running sum.
    for tag, slot in by_tag.items():
        n = slot["total"] or 1
        slot["avg_latency_s"] = round(slot.pop("_elapsed_sum") / n, 3)

    # Per-suite roll-up — grades against each suite's advisory
    # threshold so the report says "routing FAIL (passed below 0.85)"
    # instead of just dumping counts. Per-suite latency added so a
    # regression that slows multistep without changing pass-rate is
    # still visible in the report.
    suites: dict[str, dict[str, Any]] = {}
    for name, spec in SUITES.items():
        suite_rows = _suite_rows(rows, name)
        if not suite_rows:
            continue
        s_total = len(suite_rows)
        s_passed = sum(1 for r in suite_rows if r.case_pass)
        rate = s_passed / s_total if s_total else 0.0
        threshold = float(spec.get("threshold", 0.0))
        s_latencies = [r.elapsed_s for r in suite_rows]
        suites[name] = {
            "total": s_total,
            "passed": s_passed,
            "pass_rate": round(rate, 3),
            "threshold": threshold,
            "meets_threshold": rate >= threshold,
            "avg_latency_s": round(sum(s_latencies) / s_total, 3),
            "p95_latency_s": round(_percentile(s_latencies, 95), 3),
            "blurb": spec.get("blurb", ""),
        }

    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "routing_passed": sum(1 for r in routing_checked if r.routing_ok),
        "routing_total": len(routing_checked),
        "answer_passed": sum(1 for r in answer_checked if r.answer_ok),
        "answer_total": len(answer_checked),
        "errors": errors,
        "elapsed_s": round(total_elapsed, 2),
        "metrics": {
            "avg_latency_s": round(avg_latency, 3),
            "p50_latency_s": round(p50, 3),
            "p95_latency_s": round(p95, 3),
            "min_latency_s": round(min_lat, 3),
            "max_latency_s": round(max_lat, 3),
            "total_tool_dispatches": total_tools,
            "avg_tools_per_turn": round(avg_tools, 2),
            "answer_tokens_total": total_answer_tokens,
            "answer_tokens_avg": round(avg_answer_tokens, 1),
            "answer_tokens_per_sec": round(tokens_per_sec, 1),
            "answer_tokens_source": tokens_source,
            "prompt_tokens_total": real_prompt_tokens,
            "cases_with_errors": errors,
            "tokens_note": (
                "real tokenizer counts from adapter usage field"
                if tokens_source == "tokenizer"
                else "whitespace-split estimate; install an adapter "
                     "that reports usage for real counts"
            ),
            # Loop-health telemetry (v1.2). TTFT percentiles use only
            # rows where the adapter reported one (streamed cloud /
            # per-token local). ``halt_reasons`` counts every turn a
            # backstop, interrupt, or budget cut short — a healthy
            # corpus run should be nearly empty here; growth is a loop
            # regression even when pass-rate holds. ``avg_iterations``
            # catches routing inefficiency (more steps for the same
            # answers).
            **_loop_health_metrics(rows),
        },
        "suites": suites,
        "by_tag": by_tag,
        "failures": [
            {"id": r.id, "prompt": r.prompt[:100],
             "tools_called": r.tools_called,
             "answer": (r.answer or "")[:200],
             "routing_ok": r.routing_ok, "answer_ok": r.answer_ok,
             "no_hallucination": r.no_hallucination,
             "clean_output": r.clean_output,
             "safety_ok": r.safety_ok, "error": r.error}
            for r in rows if not r.case_pass
        ],
        "rows": [asdict(r) for r in rows],
    }


__all__ = ["BenchRow", "run_bench", "summarise"]
