#!/usr/bin/env python3
"""Jaeger CLI — self-improving local agent.

Lifecycle, in order:

  1. Resolve the instance dir (JAEGER_INSTANCE_DIR / ~/.jaeger/<name>/).
  2. Run the setup wizard if no valid instance is on disk.
  3. Take the exclusive lockfile (refuses to start if another copy holds it).
  4. Verify manifest.json's core_version matches; refuse-to-start if not.
  5. Bind tools + memory to the instance layout.
  6. Load the in-process Gemma model.
  7. Build the PydanticAI agent with the v2 system prompt + identity.
  8. Register built-in tools, then run the skill loader (base + instance
     skills, with smoke-test gating + instance-wins-over-core resolution).
  9. Enter the chat loop (slash commands + multiline paste detection).

This file is intentionally self-contained — no imports from `memory/`,
`messaging/`, or any other framework dir. Only third-party libraries and
sibling modules under `jaeger_os/`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import select
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jaeger_os.agent.schemas.tool_registry import register_tool_from_function
from .core import credentials as creds
from jaeger_os.core.runtime import log_rotation
from jaeger_os.core.memory import memory as mem
from jaeger_os.core.prompts import prompts as prompt_module
from jaeger_os.core.runtime import tool_interrupt
from .core import tools as jaeger_tools
from jaeger_os.core.background.cron_runner import CronRunner
from jaeger_os.core.instance.instance import (
    CoreVersionMismatch,
    InstanceLayout,
    InstanceLock,
    check_manifest,
    default_instance_name,
    resolve_instance_dir,
    touch_manifest_started,
)
from jaeger_os.core.safety.permissions import (
    ConsoleConfirmationProvider,
    PermissionPolicy,
    PermissionTier,
    install_policy,
    requires_tier,
)
from jaeger_os.core.instance.schemas import CORE_VERSION, Config
from jaeger_os.core.instance.schemas import load_yaml
from jaeger_os.core.skills.skill_loader import load_and_register
from jaeger_os.core.instance.setup_wizard import run_wizard


# ---------------------------------------------------------------------------
# Skip-final tools — DISABLED 2026-05-26.
#
# Historical context: this set listed tools whose dict result was
# treated as "the answer", short-circuiting the agent loop after the
# first tool call. A bounded 120-token finalize pass formatted the
# result into a brief user-facing sentence. Saved ~1-3s per turn on
# simple queries.
#
# Why removed: skip-final bypasses the agent's actual reasoning. The
# model never gets a chance to:
#   - decide whether the result fully answers the question
#   - catch + retry a wrong tool call
#   - chain into a follow-up step
#   - shape the answer to the user's conversational tone
#
# In practice this produced robotic-feeling answers ("workspace/haiku.txt",
# "2026-05-26 10:13:19 PM PDT") instead of natural ones. It also
# created brittle coupling between this list and the system prompt
# rules — e.g. the rule "call get_time before schedule_prompt" was
# silently broken by get_time being in skip-final, which exited the
# loop before schedule_prompt could fire.
#
# Empty set = every turn runs the full agent loop, every time. The
# ~1-3s latency cost on pure single-tool queries (calculate, recall,
# get_time, etc.) is the price of a coherent reasoning surface. If
# we ever want this back, do it as an opt-in per-turn signal from
# the model rather than a static list.
# ---------------------------------------------------------------------------
SKIP_FINAL_TOOLS: frozenset[str] = frozenset()


def _format_tool_result_as_answer(name: str, result: Any) -> str:
    """Render a tool result dict into a one-line plain string."""
    if not isinstance(result, dict):
        return str(result)
    if name == "get_time":
        return result.get("datetime") or "Time unavailable."
    if name == "calculate":
        if result.get("error"):
            expr = result.get("expression", "expression")
            return f"Couldn't calculate {expr!r}: {result['error']}"
        v = result.get("result")
        return str(v) if v is not None else "Calculation failed."
    if name == "system_status":
        disk = result.get("disk") or {}
        if disk:
            return (f"disk {disk.get('used_gb', 0):.1f}/{disk.get('total_gb', 0):.1f} GB "
                    f"({disk.get('free_gb', 0):.1f} GB free)")
        return "System status unavailable."
    if name == "list_facts":
        facts = result.get("facts") or {}
        if not facts:
            return "No facts saved yet."
        by_cat = result.get("by_category") or {}
        if by_cat:
            return " | ".join(
                f"[{cat}] " + ", ".join(f"{k}: {v}" for k, v in kv.items())
                for cat, kv in by_cat.items()
            )
        return "; ".join(f"{k}: {v}" for k, v in facts.items())
    if name == "recall":
        return str(result.get("value", "")) if result.get("found") else f"No value for {result.get('key')!r}."
    if name == "remember":
        if not result.get("remembered"):
            return "Couldn't save that."
        cat = result.get("category")
        suffix = f" under {cat}" if cat and cat != "general" else ""
        return f"Got it — remembered {result.get('key')!r}{suffix}."
    if name == "forget":
        return (f"Forgot {result.get('key')!r}." if result.get("forgotten")
                else f"No saved value under {result.get('key')!r}.")
    if name == "write_file":
        if not result.get("written"):
            return f"Couldn't write: {result.get('error')}"
        commit = result.get("commit")
        commit_suffix = f" [git {commit}]" if commit else ""
        base = f"Wrote {result.get('path')} ({result.get('bytes')} bytes).{commit_suffix}"
        # Phase-2 auto-syntax-check feedback (only present for .py files).
        if result.get("syntax_ok") is False:
            return f"{base}\nSYNTAX ERROR: {result.get('syntax_error')}"
        return base
    if name == "append_file":
        if not result.get("appended"):
            return f"Couldn't append: {result.get('error')}"
        commit = result.get("commit")
        commit_suffix = f" [git {commit}]" if commit else ""
        base = f"Appended {result.get('bytes')} bytes to {result.get('path')}.{commit_suffix}"
        if result.get("syntax_ok") is False:
            return f"{base}\nSYNTAX ERROR: {result.get('syntax_error')}"
        return base
    if name == "patch":
        if not result.get("edited"):
            return f"Couldn't edit: {result.get('error')}"
        commit = result.get("commit")
        commit_suffix = f" [git {commit}]" if commit else ""
        reps = result.get("replacements", 1)
        base = f"Edited {result.get('path')} ({reps} replacement{'s' if reps != 1 else ''}).{commit_suffix}"
        if result.get("syntax_ok") is False:
            return f"{base}\nSYNTAX ERROR: {result.get('syntax_error')}"
        return base
    if name == "delete_file":
        if not result.get("deleted"):
            return f"Couldn't delete: {result.get('reason') or result.get('error')}"
        commit = result.get("commit")
        suffix = f" [git {commit}]" if commit else ""
        return f"Deleted {result.get('path')}.{suffix}"
    if name == "read_file":
        return (result.get("content") or "")[:8000] if result.get("read") else f"Couldn't read: {result.get('error')}"
    if name == "list_skill_dir":
        if not result.get("listed"):
            return f"Couldn't list: {result.get('error')}"
        entries = result.get("entries") or []
        if not entries:
            return f"{result.get('path')}/ is empty."
        return "\n".join(f"  {e['type'][0]} {e['name']}" for e in entries)
    if name == "clarify":
        return str(result.get("question") or "")
    if name == "schedule_prompt":
        return (f"Scheduled {result.get('name')!r} — next run at {result.get('next_run_at')!r}."
                if result.get("scheduled") else f"Couldn't schedule: {result.get('error')}")
    if name == "cancel_schedule":
        return (f"Cancelled {result.get('name')!r}." if result.get("cancelled")
                else f"No schedule {result.get('name')!r}.")
    if name == "help_me":
        return result.get("summary") or ""
    if name == "list_credentials":
        names = result.get("credentials") or []
        return ("Credentials: " + ", ".join(names)) if names else "No credentials stored yet."
    if name == "reload_skills":
        newly = result.get("newly_registered") or []
        skipped = result.get("skipped") or []
        bits = []
        if newly:
            bits.append("Registered: " + ", ".join(f"{s['name']}_v{s['version']}" for s in newly))
        else:
            bits.append("No new skills to register.")
        if skipped:
            bits.append("Skipped: " + ", ".join(
                f"{s['name']}_v{s['version']} ({s['reason'][:60]})" for s in skipped
            ))
        return " ".join(bits)
    if name == "text_to_speech":
        if result.get("spoken") is True:
            # Echo the spoken line so a CLI turn isn't a bare tool entry
            # with no answer. Shown verbatim — _fast_finalize passes
            # text_to_speech through without an LLM rephrase.
            spoken = (result.get("text") or "").strip()
            return f"🔊 {spoken}" if spoken else "Spoken aloud."
        return f"Couldn't speak: {result.get('reason', 'unknown')}"
    if name == "open_on_host":
        if result.get("opened"):
            what = result.get("url") or result.get("path") or result.get("app") or ""
            return f"Opened {what}."
        return f"Couldn't open: {result.get('error', 'unknown')}"
    if name == "delegate_task":
        if result.get("delegated"):
            return str(result.get("answer") or "")
        return f"Delegation failed: {result.get('error', 'unknown')}"
    if name == "send_message":
        if result.get("sent"):
            return "Sent."
        return f"Couldn't send: {result.get('error', 'unknown')}"
    if name == "web_search":
        if result.get("error"):
            tried = result.get("tried") or []
            tail = ("\n  tried: " + "; ".join(tried)) if tried else ""
            return f"Search failed: {result['error']}{tail}"
        results = result.get("results") or []
        if not results:
            return f"No results for {result.get('query', '')!r}."
        lines = []
        for r in results[:5]:
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            snippet = (r.get("snippet") or "").strip()
            if len(snippet) > 200:
                snippet = snippet[:200].rstrip() + "…"
            lines.append(f"• {title}\n  {url}\n  {snippet}")
        backend = result.get("backend")
        # Only call out the backend when it's NOT the preferred one —
        # users don't need to know "ddgs served you" on every search,
        # but they DO want to know "this came from Wikipedia fallback".
        if backend and backend != "ddgs":
            lines.append(f"\n[via {backend} fallback]")
        return "\n".join(lines)
    if name == "get_weather":
        if result.get("error"):
            return f"Weather lookup failed: {result['error']}"
        weather = result.get("weather") or ""
        location = result.get("location") or ""
        return f"{location}: {weather}" if location else weather or "Weather unavailable."
    if name == "list_plugins":
        if result.get("error"):
            return f"Plugins unavailable: {result['error']}"
        plugins = result.get("plugins") or []
        if not plugins:
            return "No plugins found."
        lines = []
        for p in plugins:
            status = p.get("status", "unknown")
            desc = (p.get("description") or "").split("\n")[0]
            lines.append(f"• {p['name']} — {status}: {desc}")
        return "\n".join(lines)
    if name == "setup_plugin":
        if result.get("error"):
            return f"Setup unavailable: {result['error']}"
        plugin = result.get("plugin") or "(unknown)"
        steps = result.get("steps") or []
        header = f"Setup for {plugin}:"
        return header + "\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
    if name == "listen":
        if not result.get("ok"):
            return f"Couldn't listen: {result.get('error', 'unknown')}"
        text = (result.get("transcript") or "").strip()
        if not text:
            return f"(no speech detected in {result.get('seconds')}s)"
        return f"Heard: {text}"
    if name == "board_add":
        if not result.get("ok"):
            return f"Couldn't add card: {result.get('error', 'unknown')}"
        return f"Added card {result.get('card_id')} — {result.get('title')!r} → {result.get('column')}."
    if name == "board_move":
        if not result.get("ok"):
            return f"Couldn't move card: {result.get('error', 'unknown')}"
        return f"Moved {result.get('card_id')} → {result.get('column')}."
    if name == "board_update":
        if not result.get("ok"):
            return f"Couldn't update card: {result.get('error', 'unknown')}"
        return f"Updated {result.get('card_id')} ({', '.join(result.get('updated') or [])})."
    return str(result)


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------
_DEFAULT_SESSION_KEY = "cli"


def _parse_toolsets_env() -> frozenset[str] | None:
    """Parse ``JAEGER_TOOLSETS=name1,name2`` into a frozenset, or
    return ``None`` when unset / empty (= expose every tool, legacy
    default). Unknown names raise eagerly so a typo doesn't silently
    leave the agent with no tools.

    Convenience env-var hookup pending a proper ``config.toolsets:``
    field. Most users will graduate to setting the toolset via a
    slash command (``/toolsets``) once that lands."""
    raw = os.environ.get("JAEGER_TOOLSETS", "").strip()
    if not raw:
        return None
    names = frozenset(n.strip() for n in raw.split(",") if n.strip())
    if not names:
        return None
    # Validate eagerly via ``resolve_toolsets`` — its KeyError carries
    # the offending name. Catch it here so we can decorate the error
    # with the env-var context.
    from jaeger_os.agent.schemas.toolsets import resolve_toolsets
    try:
        resolve_toolsets(names)
    except KeyError as exc:
        raise ValueError(
            f"JAEGER_TOOLSETS contains an unknown toolset {exc}; "
            f"see ``jaeger_os.agent.JAEGER_TOOLSETS`` for valid names."
        ) from exc
    return names
_MAX_HISTORY_MESSAGES = 20

_pipeline: dict[str, Any] = {
    "layout": None,
    "config": None,
    "system_prompt": "",
    # Phase-7: when set to a non-empty set, the agent loop's tool
    # catalogue is filtered to just those Hermes-style toolset names.
    # ``None`` (default) means "every registered tool" — useful while
    # we measure context savings against the legacy default. Read by
    # ``_run_turn_via_jaeger_agent`` / ``prewarm`` / ``delegate_task``
    # whenever a fresh ``JaegerAgent`` is built. Override at boot via
    # the ``JAEGER_TOOLSETS`` env var (comma-separated names).
    "toolsets": None,
    "llm_lock": None,
    "show_latency": False,
    "show_tool_activity": True,
    "show_help_on_start": True,
    # Whether the KV cache has been primed with the system prompt + tool
    # schema (set by `prewarm`). Once True, the first user-facing turn
    # skips its cold-cache prefill penalty. Mirrors python_pydantic_ai.
    "prewarmed": False,
    # When False (default), every prompt runs with a fresh context — no
    # prior turns are loaded from the episodic log, no in-process history
    # is accumulated across turns. Mirrors python_pydantic_ai, which
    # gates the same path behind --with-memory. Routing benchmarks need
    # this OFF: by prompt 23, an accumulated history of 22 turns dilutes
    # the MANDATORY rules at the top of the system prompt enough to
    # cost ~3/23 on Gemma 4.
    "with_memory": False,
    # MCP (Model Context Protocol) bridge — when on, jaeger connects to
    # configured MCP servers at startup and re-exports their tools through
    # the same agent surface. Each server's tools are registered dynamically
    # from their JSON Schema, so adding a server takes no code change.
    "with_mcp": False,
    "mcp_specs": [],
    # Background ThinkingRunner — fires a chain-of-thought call after each
    # user turn on a single-worker pool, sharing the same LLM lock so it
    # never decodes against the main loop. Logs to plugins/thinking.jsonl.
    "with_thinking": False,
    "thinking_runner": None,
    # The active llama-cpp client (set by init_extensions). Plugins reach
    # back through this when they need to issue their own LLM calls.
    "client": None,
    # OpenAI-format tool schemas from the most recent decide call.
    # _fast_finalize passes these to its bounded chat call so it renders
    # the SAME <system + tools> prompt prefix — without it the finalize
    # evicts the tool-schema KV and every following turn cold-prefills
    # ~60 schemas (the ~12s/turn regression).
    "openai_tools": None,
    # /goal — session-scoped completion condition. When set, the TUI
    # REPL runs an evaluator after each turn; if the goal isn't met,
    # it auto-fires the next turn with the evaluator's reason as the
    # prompt. Mirrors Claude Code's /goal (see code.claude.com/docs/en/goal).
    "goal": None,  # GoalState | None
    # Phase-9 status indicator (Hermes-style). The TUI status bar and
    # the run-turn spinner both read this on every render tick to show
    # what the agent is actively doing — standby / model-thinking /
    # tool dispatch / deep-think / background process. Updated by
    # ``set_agent_status`` from the agent loop's callbacks and from
    # the deep-think runner / background process tracker.
    "agent_status": {
        "state": "ready",          # ready | thinking | tool | deep_think | background | finalizing | error
        "detail": "",              # short human label (tool name, queue size, …)
        "since_ts": 0.0,           # time.time() when this state started
    },
    # Phase-9 JaegerAgent currently executing a foreground turn. The
    # TUI's process-wide cancel event is not the same object as the
    # agent-loop interrupt event, so request_turn_cancel fans out to
    # this handle too.
    "active_jaeger_agent": None,
}


def set_agent_status(
    state: str,
    detail: str = "",
    *,
    since_ts: float | None = None,
) -> None:
    """Single setter the TUI / gateway / log readers poll.

    Cheap dict write — fires from anywhere (agent callback, deep-think
    runner thread, tool body). The TUI's Live spinner refreshes 8× a
    second and re-reads this; no need for a separate signal channel.
    """
    _pipeline["agent_status"] = {
        "state": state,
        "detail": detail,
        "since_ts": since_ts if since_ts is not None else time.time(),
    }


def get_agent_status() -> dict[str, Any]:
    """Snapshot of the current status, safe to read from any thread."""
    return dict(_pipeline.get("agent_status") or {
        "state": "ready", "detail": "", "since_ts": 0.0,
    })


_STATUS_GLYPHS: dict[str, str] = {
    "ready": "o",
    "thinking": "(...)",
    "tool": ">",
    "finalize": "*",
    "deep_think": "DT",
    "background": "BG",
    "error": "!",
    "speaking": "TTS",
}


def status_label(status: "dict[str, Any] | None" = None) -> str:
    """Render the current status as a short label like ``> web_search``
    or ``(...) thinking 4.2s``.  Used by the TUI spinner text and the
    bottom status bar so the user can see at a glance whether the
    agent is idle, doing model work, dispatching a tool, or busy with
    a background task.

    Pass an explicit snapshot to avoid re-read races; omit for the
    live snapshot.
    """
    snap = status if status is not None else get_agent_status()
    state = snap.get("state") or "ready"
    detail = snap.get("detail") or ""
    since = float(snap.get("since_ts") or 0.0)
    elapsed = max(0.0, time.time() - since) if since else 0.0
    glyph = _STATUS_GLYPHS.get(state, "*")
    parts = [glyph, state]
    if detail:
        parts.append(f": {detail}")
    if state != "ready" and elapsed > 0.5:
        parts.append(f"({elapsed:.1f}s)")
    return " ".join(parts)

_session_histories: dict[str, list[Any]] = {}
_session_loaded: set[str] = set()
_session_state: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# /goal — autonomous completion condition (Claude-Code-style)
#
# Set via slash command in the TUI. Each goal carries: the condition
# text, a turn counter, token-spend counter, started_at timestamp, the
# most recent evaluator reason, and a hard iteration cap so a misjudged
# goal can't loop forever.
# ---------------------------------------------------------------------------
@dataclass
class GoalState:
    condition: str
    started_at: float = field(default_factory=time.time)
    turns_evaluated: int = 0
    tokens_spent: int = 0
    last_reason: str = ""
    max_iterations: int = 20            # hard cap mirroring Claude's default
    achieved: bool = False              # set True when eval returns "yes"
    achieved_at: float | None = None

    def elapsed_s(self) -> float:
        return time.time() - self.started_at


def get_goal() -> "GoalState | None":
    """Return the active GoalState, or None when no goal is set."""
    return _pipeline.get("goal")


def set_goal(condition: str, *, max_iterations: int = 20) -> "GoalState":
    """Install a new goal, replacing any previously-active one."""
    g = GoalState(condition=condition.strip(), max_iterations=max_iterations)
    _pipeline["goal"] = g
    return g


def clear_goal() -> "GoalState | None":
    """Remove the active goal. Returns whatever was there (for logging)."""
    prior = _pipeline.get("goal")
    _pipeline["goal"] = None
    return prior


_GOAL_CLARIFY_DIRECTIVE = (
    "A user just set this goal:\n---\n{condition}\n---\n\n"
    "List up to THREE short clarifying questions whose answers would "
    "genuinely change how you approach it — scope, missing specifics, or "
    "what 'done' means. Ask only what is truly necessary; a well-specified "
    "goal needs none.\n\n"
    "Output ONLY the questions, one per line, no numbering. If the goal is "
    "already clear enough to start, output exactly: NONE"
)


def clarify_goal(client: Any, condition: str) -> list[str]:
    """Ask the model for up to 3 clarifying questions about a goal.

    Returns ``[]`` when the goal is already clear or on any failure — a
    caller treats an empty list as 'nothing to ask, proceed'."""
    if client is None or not hasattr(client, "chat"):
        return []

    def _ask() -> str:
        result = client.chat(
            [
                {"role": "system",
                 "content": "You scope tasks crisply and briefly."},
                {"role": "user",
                 "content": _GOAL_CLARIFY_DIRECTIVE.format(condition=condition)},
            ],
            max_tokens=200, temperature=0.3, top_p=0.9, stream=False,
        )
        return (getattr(result, "text", None) or "").strip()

    lock = _pipeline.get("llm_lock")
    try:
        if lock is not None:
            with lock:
                text = _ask()
        else:
            text = _ask()
    except Exception:
        return []
    if not text or text.upper().startswith("NONE"):
        return []
    questions: list[str] = []
    for line in text.splitlines():
        q = line.strip().lstrip("0123456789.)-•* ").strip()
        if q and "?" in q and q.upper() != "NONE":
            questions.append(q)
    return questions[:3]


def refresh_identity() -> None:
    """Rebuild the system prompt from identity.yaml / soul.md and drop the
    cached agent, so a self-update (``set_name`` / ``update_soul``) is live
    on the next turn. Best-effort — a failure just defers the change to the
    next reboot."""
    layout = _pipeline.get("layout")
    if layout is None:
        return
    try:
        _pipeline["system_prompt"] = prompt_module.build_system_prompt(layout)
    except Exception:  # noqa: BLE001
        pass
    try:
        _agent_cache.clear()
    except Exception:  # noqa: BLE001
        pass


_GOAL_EVAL_DIRECTIVE = (
    "You are evaluating whether a session goal has been achieved. The goal:\n"
    "---\n{condition}\n---\n\n"
    "Look at the conversation transcript so far. The assistant has been "
    "working toward the goal. Decide:\n"
    "  * MET   — the condition is now satisfied based on what the assistant "
    "has surfaced in the transcript (tool results, files written, "
    "explanations given).\n"
    "  * NOT MET — the condition is not yet satisfied. Give a SHORT (one "
    "sentence) reason explaining what is still missing or what the "
    "assistant should do next.\n\n"
    "Reply with exactly one of these formats, nothing else:\n"
    "  MET: <one sentence summary of why the goal is satisfied>\n"
    "  NOT MET: <one sentence on what's still needed>"
)


def evaluate_goal(
    client: Any,
    goal: "GoalState",
    transcript_tail: str,
) -> tuple[bool, str]:
    """Run the goal evaluator. Returns ``(met, reason)``.

    Uses a bounded ``client.chat`` call (max_tokens=120, temp=0) so the
    per-turn evaluation cost stays small — same pattern as
    ``_fast_finalize_sync``. Falls back to (False, error) on any model
    failure so the caller can decide to stop the loop."""
    directive = _GOAL_EVAL_DIRECTIVE.format(condition=goal.condition)
    try:
        result = client.chat(
            [
                {"role": "system",
                 "content": "You are a precise goal evaluator. Reply in "
                            "the exact MET/NOT MET format requested."},
                {"role": "user",
                 "content": f"Conversation tail:\n{transcript_tail[-4000:]}"},
                {"role": "user", "content": directive},
            ],
            max_tokens=120,
            temperature=0.0,
            top_p=0.9,
            stream=False,
        )
        text = (getattr(result, "text", None) or "").strip()
    except Exception as exc:  # noqa: BLE001
        return False, f"evaluator error: {exc}"

    upper = text.upper()
    if upper.startswith("MET:") or upper.startswith("MET ") or upper == "MET":
        reason = text.split(":", 1)[1].strip() if ":" in text else text
        return True, reason
    if upper.startswith("NOT MET"):
        reason = text.split(":", 1)[1].strip() if ":" in text else text
        return False, reason
    # Ambiguous output: assume not met and surface the raw text as reason.
    return False, f"(ambiguous eval output) {text[:200]}"


@dataclass
class LatencyReport:
    total: float
    tool_calls: int
    decision: float
    decision_ttft: float
    tool: float
    final: float
    final_ttft: float


def print_latency(report: LatencyReport) -> None:
    print("Latency:")
    print(f"- decision: {report.decision:.3f}s  (ttft {report.decision_ttft:.3f}s)")
    print(f"- tool: {report.tool:.3f}s")
    print(f"- final: {report.final:.3f}s  (ttft {report.final_ttft:.3f}s)")
    print(f"- total: {report.total:.3f}s  (tool_calls: {report.tool_calls})")


def write_log(entry: dict[str, Any]) -> None:
    layout: InstanceLayout = _pipeline["layout"]
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "framework": "jaeger_os",
        "core_version": CORE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **entry,
    }
    with layout.latency_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")
    if _pipeline["with_memory"]:
        _record_episodic(entry)


def _record_episodic(entry: dict[str, Any]) -> None:
    user = entry.get("user")
    if not user:
        return
    try:
        mem.append_episodic({
            "timestamp": entry.get("timestamp"),
            "framework": "jaeger_os",
            "session_key": entry.get("session_key"),
            "user": user,
            "decision_raw": json.dumps(entry.get("decision"), ensure_ascii=True, default=str)
                if entry.get("decision") is not None else None,
            "answer": entry.get("answer"),
        })
    except Exception as exc:
        print(f"[jaeger] episodic append failed: {exc}", file=sys.stderr, flush=True)


def _get_session_history(session_key: str) -> list[Any]:
    """The in-process conversation history for a session.

    A session starts with a CLEAN slate. Prior sessions are NOT blindly
    replayed into context — that bled stale, already-finished tasks from
    past sessions into new ones (e.g. re-opening a calculator nobody asked
    about). Past turns live in episodic memory; the agent retrieves what is
    relevant on demand with `search_memory` / `memory(recall)`. The list
    here accumulates only as the live session runs.
    """
    history = _session_histories.get(session_key)
    if history is None:
        history = []
        _session_histories[session_key] = history
    return history


def reset_session(session_key: str = _DEFAULT_SESSION_KEY) -> int:
    """Clear a session's in-process conversation history (the ``/new``
    command). Returns the number of messages dropped. Episodic memory
    on disk is untouched — only the live context window is reset; the
    session stays marked loaded so old turns are not re-resumed.

    Phase-9 conversation state lives on ``JaegerAgent.messages`` for
    sessions that have been routed through the new agent path. We MUST
    clear that list too — otherwise ``/new`` looks like a no-op from
    the operator's view but the next turn still sees the old context."""
    legacy_dropped = 0
    history = _session_histories.get(session_key)
    if history is not None:
        legacy_dropped = len(history)
        history.clear()
    # Phase-9 path: drop the JaegerAgent's internal messages too.
    agent_dropped = 0
    agent = _jaeger_agents_by_session.get(session_key)
    if agent is not None and hasattr(agent, "messages"):
        agent_dropped = len(agent.messages)
        agent.messages.clear()
    _session_loaded.add(session_key)
    _session_state.pop(session_key, None)
    return legacy_dropped + agent_dropped


def pop_last_exchange(session_key: str = _DEFAULT_SESSION_KEY) -> str | None:
    """Drop the most recent user→assistant exchange from a session's
    history (``/undo`` / ``/retry``). Returns the user text of that
    exchange so ``/retry`` can re-send it, or ``None`` when there is
    nothing to drop.

    Prefers the Phase-9 ``JaegerAgent.messages`` list when one exists
    for the session — that's where the live conversation actually
    lives. Falls back to the legacy ``_session_histories`` shape for
    hybrid sessions that ran through the pre-Phase-9 loop."""
    # ── Phase-9 path: dict-shape messages on the agent. ─────────────
    agent = _jaeger_agents_by_session.get(session_key)
    if agent is not None and getattr(agent, "messages", None):
        msgs = agent.messages
        cut = None
        user_text: str | None = None
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            if isinstance(m, dict) and m.get("role") == "user":
                cut = i
                user_text = str(m.get("content") or "")
                break
        if cut is not None:
            del msgs[cut:]
            return user_text
    # ── Legacy pydantic-ai path (kept for hybrid sessions). ────────
    history = _session_histories.get(session_key)
    if not history:
        return None
    cut = None
    user_text = None
    for i in range(len(history) - 1, -1, -1):
        for part in getattr(history[i], "parts", []):
            if getattr(part, "part_kind", None) == "user-prompt":
                cut = i
                user_text = str(getattr(part, "content", "") or "")
                break
        if cut is not None:
            break
    if cut is None:
        return None
    del history[cut:]
    return user_text


def _session_context_block(session_key: str, user_text: str) -> str:
    """Return a compact context block for follow-up turns.

    This is intentionally tiny and derived from trusted tool returns, not a
    prose summary. It gives the local model anchors for phrases like "that
    result" without replaying a long transcript.
    """
    state = _session_state.get(session_key) or {}
    if not state:
        return ""
    lower = (user_text or "").lower()
    followup = bool(re.search(
        r"\b(that|it|there|same|previous|last)\b|what about",
        lower,
    ))
    if not followup and len(state) > 2:
        return ""
    lines: list[str] = []
    if state.get("last_calculation_result") is not None:
        lines.append(f"last_calculation_result: {state['last_calculation_result']}")
    if state.get("last_location"):
        lines.append(f"last_location: {state['last_location']}")
    if state.get("last_file"):
        lines.append(f"last_file: {state['last_file']}")
    if state.get("last_search_topic"):
        lines.append(f"last_search_topic: {state['last_search_topic']}")
    if not lines:
        return ""
    return "[session context from prior tool results]\n" + "\n".join(lines) + "\n[end session context]"


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------
def _register_builtins(client: Any) -> None:
    """Wire all the built-in Jaeger tools into the framework-free
    :mod:`jaeger_os.agent.schemas.tool_registry`.

    Phase-6.2 cutover: the decorator is now ``@register_tool_from_function``
    (was ``@agent.tool_plain``); tool bodies and the ``@requires_tier``
    safety decorator are unchanged. Skill-loader-managed skills come
    AFTER this — instance skills can override built-ins by registering
    a higher version of the same name (last-write-wins in the registry).
    """
    t = jaeger_tools

    @register_tool_from_function
    @requires_tier(PermissionTier.READ_ONLY, skill="time", operation="get_time",
                   summary="read the current time")
    def get_time(timezone: str | None = None) -> dict:
        """The current date, day of the week, year, and time — the ONLY
        source of truth for "what day/date/year/time is it", "what's
        today", and similar. Your training data is frozen in the past, so
        a date or year answered from memory will be WRONG — always call
        this for anything about the present moment. Optional IANA
        timezone (e.g. 'Asia/Shanghai')."""
        return t.get_time(timezone=timezone)

    @register_tool_from_function
    @requires_tier(PermissionTier.READ_ONLY, skill="math", operation="calculate",
                   summary="evaluate an arithmetic expression")
    def calculate(expression: str) -> dict:
        """Evaluate a safe arithmetic expression. Supports + - * / ** % //
        and single-arg sqrt/abs/log/log10/exp/sin/cos/tan/floor/ceil/round.
        For "square root of N" call calculate("sqrt(N)")."""
        return t.calculate(expression=expression)

    @register_tool_from_function
    @requires_tier(PermissionTier.READ_ONLY, skill="host", operation="system_status",
                   summary="read machine + instance dir status")
    def system_status() -> dict:
        """Machine health only: CPU, memory, disk, and instance metadata.
        Do NOT use this to list workspace files; use list_skill_dir for
        "list the workspace", "show files", or "what files are here"."""
        return t.system_status()

    @register_tool_from_function
    @requires_tier(PermissionTier.WRITE_LOCAL, skill="files",
                   operation="write_file",
                   summary="write a file in the skills workspace")
    def write_file(path: str, content: str) -> dict:
        """Write a text file in the sandboxed skills/ directory. Overwrites
        if it already exists."""
        return t.file_write(path=path, content=content)

    @register_tool_from_function
    @requires_tier(PermissionTier.WRITE_LOCAL, skill="files",
                   operation="append_file",
                   summary="append to a file in the skills workspace")
    def append_file(path: str, content: str) -> dict:
        """Append text to an existing skills/ file."""
        return t.append_file(path=path, content=content)

    @register_tool_from_function
    @requires_tier(PermissionTier.WRITE_LOCAL, skill="files",
                   operation="patch",
                   summary="edit a file in the skills workspace")
    def patch(path: str, old: str, new: str, replace_all: bool = False) -> dict:
        """Surgically edit an EXISTING skills/ file by find-and-replace.
        Prefer this over write_file to change a file you've already
        written — it swaps one region instead of regenerating the whole
        file, so a long file can't be lost to a truncated rewrite. `old`
        must be a snippet that occurs exactly once (pass a longer unique
        snippet if it isn't), or set replace_all=true to change every
        occurrence."""
        return t.edit_file(path=path, old=old, new=new, replace_all=replace_all)

    @register_tool_from_function
    @requires_tier(PermissionTier.WRITE_LOCAL, skill="files",
                   operation="delete_file",
                   summary="delete a file from the skills workspace")
    def delete_file(path: str) -> dict:
        """Delete a file from the skills/ directory."""
        return t.delete_file(path=path)

    @register_tool_from_function
    @requires_tier(PermissionTier.READ_ONLY, skill="files", operation="read_file",
                   summary="read a workspace file")
    def read_file(path: str, offset: int = 0, limit: int | None = None) -> dict:
        """Read a text file from ANYWHERE on the machine — your own
        source code, the whole repository you run from, the wider
        system. Absolute paths and `~` work; reading is not sandboxed.
        (Off-limits: the credentials/ store and OS secret files like
        ~/.ssh.) For a large file, page it: `offset` is the 0-based
        first line, `limit` the line count (default: the whole file)."""
        return t.file_read(path=path, offset=offset, limit=limit)

    @register_tool_from_function
    @requires_tier(PermissionTier.READ_ONLY, skill="files", operation="list_skill_dir",
                   summary="list contents of the skills directory")
    def list_skill_dir(path: str = ".") -> dict:
        """List a directory's contents. With no path, lists your instance
        workspace; pass an ABSOLUTE path (or `~`) to browse ANY directory
        — your repository, the wider system. Listing is not sandboxed.
        Use for "list files", "show files", "what's in <dir>"."""
        return t.list_skill_dir(path=path)

    @register_tool_from_function
    @requires_tier(PermissionTier.READ_ONLY, skill="files", operation="search_files",
                   summary="search file contents under the skills directory")
    def search_files(query: str, path: str = ".", max_results: int = 50) -> dict:
        """Recursively grep file CONTENTS — case-insensitive substring
        match. With no path, searches the working directory; pass an
        ABSOLUTE path to search ANY directory — e.g. your whole
        repository. Searching is not sandboxed. Use this to find where
        something is defined or used instead of reading files one by
        one. Returns {file, line, text} matches."""
        return t.search_files(query=query, path=path, max_results=max_results)

    @register_tool_from_function
    def remember(key: str, value: str, category: str = "") -> dict:
        """MANDATORY when the user states a preference, identity fact,
        plan, or anything they might recall later. Call this proactively
        — do not just acknowledge "OK, I'll remember" in text. Pick a
        descriptive snake_case key.

        Set `category` to keep memory organised — a short label like
        `contacts`, `preferences`, `projects`, `schedule`; omit it for a
        miscellaneous fact. Examples: "my favorite color is teal"
        (preferences), "Sara's number is 555-0142" (contacts), "I'll be
        in Tokyo next week" (schedule). For YOUR OWN name use set_name,
        not this."""
        return t.remember(key=key, value=value, category=category)

    @register_tool_from_function
    @requires_tier(PermissionTier.READ_ONLY, skill="memory", operation="recall",
                   summary="recall a fact by key")
    def recall(key: str) -> dict:
        """MANDATORY when the user asks about something they told you
        earlier ("what did I say my…", "do you remember…", "what's my
        favorite X", "what video length do I prefer?"). Call BEFORE
        answering — the persisted store is the source of truth.
        Fuzzy match supported, so close-but-not-exact keys still hit."""
        return t.recall(key=key)

    @register_tool_from_function
    def forget(key: str) -> dict:
        """MANDATORY when the user asks to remove a stored fact
        ("forget my X", "remove my X preference", "I changed my mind
        about X"). Call this — don't just acknowledge in text."""
        return t.forget(key=key)

    @register_tool_from_function
    def set_name(name: str) -> dict:
        """Change your OWN name. Use when the user renames you ("your
        name is …", "I'll call you …", "rename yourself"). Writes your
        real identity (identity.yaml). Do NOT use remember() for your own
        name — remember() is for facts about the USER."""
        return t.set_name(name=name)

    @register_tool_from_function
    def update_soul(content: str) -> dict:
        """Rewrite your soul.md — who you are: character, values, voice,
        self-narrative. Your current soul is in your system prompt; read
        it, revise it, and pass the COMPLETE new text. Personality and
        durable facts about YOURSELF go here, not in remember()."""
        return t.update_soul(content=content)

    @register_tool_from_function
    @requires_tier(PermissionTier.READ_ONLY, skill="memory", operation="list_facts",
                   summary="list every stored fact")
    def list_facts() -> dict:
        """MANDATORY for open-ended "what do you know about me?" or
        "what have I told you?" questions. Returns the full k/v store.
        Use this before falling back to free-text 'I don't know'."""
        return t.list_facts()

    @register_tool_from_function
    def memory(action: str, key: str = "", value: str = "",
               query: str = "", category: str = "") -> dict:
        """The agent's persistent memory — one tool, action-dispatched.
        ``action`` ∈ remember / recall / forget / list / search.
        ``remember`` takes key+value (and optional category);
        ``recall`` / ``forget`` take key; ``search`` takes query.
        See ``describe_tool("memory")`` for the full when-to-call
        contract — the prompt's MANDATORY_TOOL_RULES section also
        covers it."""
        return t.memory(action=action, key=key, value=value,
                        query=query, category=category)

    @register_tool_from_function
    def schedule_prompt(cron_expr: str, prompt: str, name: str | None = None) -> dict:
        """Schedule a prompt for unattended execution on a cron expression."""
        return t.schedule_prompt(cron_expr=cron_expr, prompt=prompt, name=name)

    @register_tool_from_function
    def list_schedules() -> dict:
        """List every active scheduled prompt."""
        return t.list_schedules()

    @register_tool_from_function
    def cancel_schedule(name: str) -> dict:
        """Cancel a previously-scheduled prompt by name."""
        return t.cancel_schedule(name=name)

    @register_tool_from_function
    def web_search(query: str, max_results: int = 5) -> dict:
        """Web search (multi-backend, no API key). Returns titles + URLs
        + snippets. Use this to FIND relevant pages, then web_extract to
        actually READ one."""
        return t.web_search(query=query, max_results=max_results)

    @register_tool_from_function
    def web_extract(url: str, max_chars: int = 8000) -> dict:
        """Fetch a web page and return its readable text. This is the
        research tool — web_search finds which pages matter, web_extract
        reads one. Use it to pull library docs, API references, Stack
        Overflow answers, READMEs — anything you need to understand
        before writing code for an unfamiliar task."""
        return t.web_fetch(url=url, max_chars=max_chars)

    @register_tool_from_function
    def get_weather(location: str) -> dict:
        """Look up current weather via wttr.in (no API key)."""
        return t.get_weather(location=location)

    @register_tool_from_function
    @requires_tier(PermissionTier.WRITE_LOCAL, skill="code",
                   operation="execute_code",
                   summary="run Python code in the skills workspace")
    def execute_code(code: str, timeout_s: float = 10.0) -> dict:
        """Run Python code and return its output. Reach for this for
        computational work: arithmetic that can't be done with
        `calculate`, string transforms, quick logic — and to run files
        you wrote with write_file (code runs IN the skills/ workspace,
        so `import name` and `open('file')` see them). 10s default
        timeout. Isolated from packages installed via install_package.

        For the current date / day / time / timezone, use `get_time` —
        it's the ONLY source of truth, not Python's clock."""
        return t.run_python(code=code, timeout_s=timeout_s)

    @register_tool_from_function
    def terminal(command: str, timeout_s: float = 60.0) -> dict:
        """Run a non-Python command-line program — git, npm, brew,
        ffmpeg. For Python code use execute_code; for files use
        write_file / read_file / list_skill_dir. PRIVILEGED-tier: each
        call prompts the user, so reach for it only when the task
        genuinely needs a shell program."""
        return t.run_shell(command=command, timeout_s=timeout_s)

    @register_tool_from_function
    def remote_terminal(host: str, command: str, timeout_s: float = 60.0) -> dict:
        """Run one command on a REMOTE host over SSH. ``terminal`` runs
        locally; this runs the same shape of command on another machine.
        ``host`` follows ssh's destination grammar — ``[user@]host[:port]``
        or any ``Host`` alias from ~/.ssh/config. Auth uses the local
        user's ssh keychain (BatchMode=yes — no password prompts; missing
        key fails fast). PRIVILEGED-tier, audited like ``terminal``."""
        return t.ssh_exec(host=host, command=command, timeout_s=timeout_s)

    @register_tool_from_function
    def install_package(package: str) -> dict:
        """Install a third-party Python package into this instance's
        own venv (isolated from the framework). Use when a skill you're
        building needs a library — e.g. `discord.py` for a Discord
        integration. PRIVILEGED tier: routes through the confirmation
        flow. After installing, use run_in_venv (not run_python) to run
        code that imports it."""
        return t.install_package(package=package)

    @register_tool_from_function
    def list_venv_packages() -> dict:
        """List packages installed in this instance's venv. Read-only —
        check here before install_package to see if a dependency is
        already available."""
        return t.list_venv_packages()

    @register_tool_from_function
    def run_in_venv(code: str, timeout_s: float = 30.0) -> dict:
        """Execute Python against this instance's venv interpreter so
        packages installed via install_package ARE importable. Sandboxed
        cwd, 30s default timeout (max 300s). Use this — not run_python —
        for code that depends on installed libraries."""
        return t.run_in_venv(code=code, timeout_s=timeout_s)

    @register_tool_from_function
    def list_models() -> dict:
        """List the LLM models in the registry with role (realtime /
        coder) and cache status. Read-only — use this to tell the user
        what's available, or to back a model recommendation."""
        return t.list_models()

    @register_tool_from_function
    def download_model(name: str) -> dict:
        """Download a registered model from HuggingFace Hub. PRIVILEGED
        tier — routes through confirmation. Only call this when the user
        has explicitly asked for a model OR agreed to one you
        recommended; never speculatively. Recommend first, let the user
        decide, then call. Use list_models for valid names."""
        return t.download_model(name=name)

    @register_tool_from_function
    def model_location(action: str, path: str = "") -> dict:
        """Register a custom directory JROS scans for local .gguf models
        — so a folder you point it at (a non-standard LM Studio / Ollama
        install, your own model stash) shows up in /models and the model
        picker. action: 'add' / 'remove' / 'list'. Persisted to the
        instance config; survives restarts."""
        return t.model_location(action=action, path=path)

    @register_tool_from_function
    def package_skill(name: str) -> dict:
        """Bundle a skill you built into a portable, shareable .zip with
        a generated manifest (name, version, deps, smoke-test status).
        Use this once a skill is proven and worth sharing. The bundle
        installs on any Jaeger-OS instance. Publishing it to the
        marketplace is a later step (the marketplace repo isn't live
        yet — see docs/marketplace_spec.md)."""
        return t.package_skill(name=name)

    @register_tool_from_function
    def benchmark_skill(name: str) -> dict:
        """Run a skill's scored benchmark (tests/benchmark.py) and track
        the delta vs. its last run. Use this when revising a skill:
        benchmark the old version, write the new one, benchmark again —
        `delta > 0` proves the revision helped. Same principle as the
        repo's level benchmarks, scoped to one skill."""
        return t.benchmark_skill(name=name)

    @register_tool_from_function
    def propose_deep_think_task(description: str) -> dict:
        """Queue a skill-development task for Deep Think to work later.
        Use when you notice something worth building/fixing that's too
        big for the current turn. The task is added UNAPPROVED — the
        user approves it before Deep Think runs it. You propose; the
        user decides."""
        return t.propose_deep_think_task(description=description)

    @register_tool_from_function
    def list_deep_think_queue() -> dict:
        """Read the Deep Think task queue with status counts. Read-only."""
        return t.list_deep_think_queue()

    @register_tool_from_function
    def kanban(action: str, card_id: str = "", title: str = "",
               description: str = "", column: str = "", tag: str = "",
               priority: str = "", note: str = "") -> dict:
        """The kanban task board — ONE tool. `action` selects the op:
          • view — read the board (optional `column`/`tag` filter)
          • add — add a card (`title`, optional `description`/`priority`
            low|med|high/`tag`)
          • move — move card `card_id` to `column`
          • update — edit / log on `card_id` (`note` appends a line)
          • complete — mark `card_id` done
          • block / unblock — mark `card_id` blocked, or send it back
        Columns: backlog / ready / in_progress / blocked / done. Lay a
        multi-step task out as cards so you and the user can track it."""
        return t.kanban(action=action, card_id=card_id, title=title,
                        description=description, column=column, tag=tag,
                        priority=priority, note=note)

    @register_tool_from_function
    @requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="browser",
                   operation="browser",
                   summary="drive a real web browser")
    def browser(action: str, url: str = "", element: int = 0,
                text: str = "", direction: str = "down",
                key: str = "Enter") -> dict:
        """Drive a real web browser — one tool, action-dispatched.
        Actions: open / snapshot / click / type / scroll / back /
        press / close. Open a page → read its returned elements →
        click/type by index. See ``describe_tool("browser")`` for
        the full action map + per-action args."""
        return t.browser(action=action, url=url, element=element,
                         text=text, direction=direction, key=key)

    @register_tool_from_function
    def skill(action: str, name: str = "", query: str = "",
              file: str = "") -> dict:
        """Discover and read playbook skills — experienced procedures
        for a task. ``action`` ∈ list / search / view. Use ``search``
        FIRST when a task might have a matching playbook (the
        OPERATING_DISCIPLINE rule). ``view`` returns the full skill
        body + its bundled-file listing; pass ``file=...`` to read
        one. See ``describe_tool("skill")`` for the full contract."""
        return t.skill(action=action, name=name, query=query, file=file)

    @register_tool_from_function
    def board_view(column: str = "", tag: str = "") -> dict:
        """Read the kanban task board — what work is queued (ready),
        in_progress, blocked, or done. Optionally filter by `column` or
        `tag`. Deep Think jobs show here too (tag 'deepthink')."""
        return t.board_view(column=column, tag=tag)

    @register_tool_from_function
    def board_add(
        title: str, description: str = "",
        tags: list[str] | None = None, priority: str = "med",
    ) -> dict:
        """Add a card to the kanban board (lands in `ready`, set to
        work). Use this to lay out a multi-step task as cards so you and
        the user can track progress. `priority` is low/med/high."""
        return t.board_add(title=title, description=description,
                           tags=tags, priority=priority)

    @register_tool_from_function
    def board_move(card_id: str, column: str) -> dict:
        """Move a board card: `in_progress` when you start it, `done`
        when finished, `blocked` when it needs the user. You cannot move
        a card `backlog → ready` — that is the user's approval step."""
        return t.board_move(card_id=card_id, column=column)

    @register_tool_from_function
    def board_update(
        card_id: str, title: str = "", description: str = "",
        priority: str = "", add_tag: str = "", note: str = "",
        result: str = "",
    ) -> dict:
        """Edit a board card or log progress on it. `note` appends to
        the card's running log; `result` records the outcome. Empty
        arguments are left unchanged."""
        return t.board_update(card_id=card_id, title=title,
                              description=description, priority=priority,
                              add_tag=add_tag, note=note, result=result)

    @register_tool_from_function
    def todo(todos: list[dict] | None = None, merge: bool = False) -> dict:
        """Session task list — a scratchpad for multi-step jobs (3+
        steps or several things at once). No args = read current
        list. ``todos`` = list of ``{id, content, status}`` items
        (pending / in_progress / completed / cancelled). ``merge=False``
        (default) replaces the list; ``merge=True`` updates by id.

        Keep exactly ONE item in_progress at a time; use the kanban
        board for cross-session work. See ``describe_tool("todo")``
        for the full contract."""
        return t.todo(todos=todos, merge=merge)

    # NB: ``describe_tool`` and ``load_toolset`` are NOT redefined here.
    # Both are owned by :mod:`jaeger_os.core.tools.meta` and registered
    # at module-import time. The pre-Phase-9 pattern of wrapping each
    # built-in tool inside this closure created two copies (one in
    # ``meta.py`` and one here) that could drift; the meta module is
    # now the single source of truth. See finding #11 in
    # docs/code_review_2026_05_24.md.

    @register_tool_from_function
    def start_background(code: str, name: str = "") -> dict:
        """Launch Python code as a background process that OUTLIVES this
        turn. Use this — not run_python / run_in_venv (which are capped
        and synchronous) — for work that takes minutes or longer: a long
        render, a bot that stays connected, a watcher. Runs against the
        instance venv. Returns a process_id; monitor with
        check_background, end with stop_background."""
        return t.start_background(code=code, name=name)

    @register_tool_from_function
    def list_background() -> dict:
        """List every background process with live status (running /
        exited / stopped, exit code, elapsed)."""
        return t.list_background()

    @register_tool_from_function
    def check_background(process_id: str, lines: int = 20) -> dict:
        """Status of one background process + the last `lines` lines of
        its output (default 20, max 2000 — raise it for fuller output).
        Use it to see whether a process you started is still running and
        what it produced."""
        return t.check_background(process_id=process_id, lines=lines)

    @register_tool_from_function
    def stop_background(process_id: str) -> dict:
        """Terminate a running background process by id."""
        return t.stop_background(process_id=process_id)

    @register_tool_from_function
    def pending_background() -> dict:
        """Drain the queue of background tasks that finished since the
        last check. Each completion is surfaced at most once. Returns
        ``{completions: [...], count: N}`` — empty when nothing new has
        finished. Faster than polling ``check_background`` in a loop."""
        return t.pending_background()

    # ``system_health`` is intentionally NOT registered as an agent
    # tool — operator-only access via ``jaeger health`` CLI verb.
    # Hiding it from the model surface fixed a prefill stall: prompts
    # like "do a self check" routed across ``system_health`` /
    # ``system_status`` and llama.cpp's Metal sampler hung at high
    # first-token entropy. The underlying function is still imported
    # by the CLI verb (``daemon/health_verb.py``) and by boot
    # preflight; only the agent-facing registration is gone.

    @register_tool_from_function
    def run_benchmark(tags: str = "", limit: int = 0,
                      ids: str = "", save: bool = True) -> dict:
        """Run the agent self-benchmark against the live pipeline.
        ``tags``: comma-separated filter (routing / multistep /
        multiturn / recovery / memory / files / web / code / audio
        / schedule). ``limit``: cap cases; ``ids``: re-run specific
        case ids. Writes ``<instance>/logs/bench/<ts>/``. See
        ``describe_tool("run_benchmark")`` for the full contract."""
        return t.run_benchmark(tags=tags, limit=limit, ids=ids, save=save)

    @register_tool_from_function
    def clarify(question: str) -> dict:
        """Ask the user a clarifying question instead of guessing."""
        return t.ask_user(question=question)

    @register_tool_from_function
    def help_me() -> dict:
        """Capability overview — call when asked 'what can you do?'."""
        return t.help_me()

    @register_tool_from_function
    def get_credential(name: str) -> dict:
        """Look up a secret (API key, token) by name from the instance's
        credentials/ store. NEVER read credential files directly — this is
        the only sanctioned access path. The returned value is for tool
        use only; do NOT echo it back to the user in your reply.
        """
        return creds.get_credential_tool_result(_pipeline["layout"], name=name)

    @register_tool_from_function
    def list_credentials() -> dict:
        """List the names of every credential currently stored. Values
        are never returned by this tool — use get_credential(name) for
        the actual value, and never echo the value in your reply."""
        return {"credentials": creds.list_credentials(_pipeline["layout"])}

    # ------------------------------------------------------------------
    # Parity ports from python_pydantic_ai — TTS, vision, host, sub-agent,
    # semantic memory. Each tool's docstring is what the LLM sees.
    # ------------------------------------------------------------------
    @register_tool_from_function
    def text_to_speech(text: str = "", path: str = "") -> dict:
        """Speak text aloud through the default audio output via Kokoro
        TTS. Use ONLY when the user explicitly asks to HEAR something
        ("say…", "out loud", "narrate/read X aloud", "speak"). This is
        NOT your reply channel — ordinary questions ("tell me a joke",
        "what's the weather") are answered in text, not spoken.
        Pass `text` for literal text, or `path` to narrate a file from
        <instance>/skills/ ("read X out loud", "narrate X" with a named
        file). `path` is sandbox-resolved and wins over `text` when both
        are given. Supports minimal SSML: <break time="200ms"/>, <breath/>."""
        return t.speak(text=text, path=path)

    @register_tool_from_function
    def vision_analyze(image_path: str, question: str = "Describe this image in one short sentence.") -> dict:
        """Look at a workspace image and answer a question about it.
        Default backbone: Moondream2 (~1.9B VLM, Apache-2.0). image_path is
        sandbox-resolved under <instance>/skills/. First call lazy-loads
        the VLM on CPU."""
        return t.look_at(image_path=image_path, question=question)

    @register_tool_from_function
    @requires_tier(PermissionTier.WRITE_LOCAL, skill="vision",
                   operation="image_generate",
                   summary="generate an image into the skills workspace")
    def image_generate(
        prompt: str,
        out_path: str = "generated.png",
        num_inference_steps: int = 1,
        guidance_scale: float = 0.0,
        seed: int | None = None,
    ) -> dict:
        """Generate an image from a text prompt and save under skills/.
        Default backbone: SDXL-Turbo (1-step). First call downloads ~6 GB
        of weights; subsequent calls are 1-3s per image."""
        return t.generate_image(
            prompt=prompt, out_path=out_path,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale, seed=seed,
        )

    @register_tool_from_function
    @requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="host",
                   operation="open_on_host",
                   summary="open a URL / file / app on the host")
    def open_on_host(target: str, kind: str = "auto") -> dict:
        """Open something on the host (macOS). One verb for three cases:
        a URL in the default browser, a workspace file in its default
        app, or a macOS application by name. `kind` is "auto" (default),
        "url", "file", or "app" — "auto" classifies the target (http →
        URL, an existing skills/ file → file, else → app name). File
        targets are sandbox-resolved under <instance>/skills/."""
        return t.open_on_host(target=target, kind=kind)

    @register_tool_from_function
    def search_memory(query: str, k: int = 5) -> dict:
        """Semantic search over this instance's episodic conversation log.
        Use when `recall` (exact key) misses — e.g. "what did we talk
        about yesterday?", "did I tell you about my dog?". Returns top-k
        past turns with cosine-similarity scores."""
        return t.search_memory(query=query, k=k)

    @register_tool_from_function
    def delegate_task(subtasks: list[str]) -> dict:
        """Hand focused subtasks to fresh sub-agents. Pass a list: one
        item runs a single sub-agent; 2+ items fan out across up to 2
        concurrent sub-agents. Each sub-agent runs in its own context
        (no parent history) but shares the instance's memory and tools.
        Sub-agents share the one loaded model, so their LLM turns
        serialize — the benefit is clean fan-out/collect, not raw speed.
        Depth-limited. For sustained background work, prefer Deep Think
        (/deepthink) over delegation."""
        clean = [s for s in (subtasks or []) if s and s.strip()]
        if not clean:
            return {"delegated": False, "error": "no subtasks given"}
        if len(clean) == 1:
            return _delegate_internal(client, clean[0])
        return _delegate_parallel(client, clean)

    @register_tool_from_function
    @requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="messaging",
                   operation="send_message",
                   summary="send a message on an external channel")
    def send_message(channel: str, recipient: str, text: str) -> dict:
        """Send a proactive message to a user on a messaging channel.

        Available `channel` values depend on which bridges are live in
        this process — typically "discord", "telegram", "imessage".
        `recipient` is the channel-specific ID (numeric Discord user ID,
        Telegram chat ID, or iMessage phone/Apple-ID handle).

        Use this together with `schedule_prompt` to send unattended
        notifications: schedule a prompt that says "send the weather to
        Discord user 12345" and the cron runner will fire it on time.
        """
        text_clean = (text or "").strip()
        channel_clean = (channel or "").strip().lower()
        recipient_clean = (recipient or "").strip()
        if not channel_clean or not recipient_clean or not text_clean:
            return {"sent": False, "error": "channel, recipient, and text are all required"}
        try:
            from .plugins import get_bridge, list_bridges
        except Exception as exc:
            return {"sent": False, "error": f"messaging plugin not importable: {exc}"}
        bridge = get_bridge(channel_clean)
        if bridge is None:
            return {
                "sent": False,
                "error": f"no bridge registered for {channel_clean!r}; live bridges: {list_bridges()}",
            }
        try:
            return bridge.send(recipient_clean, text_clean)
        except Exception as exc:
            return {"sent": False, "error": f"bridge.send failed: {type(exc).__name__}: {exc}"}

    @register_tool_from_function
    def reload_skills() -> dict:
        """Re-scan core skills/ + instance skills/ and register any
        newly-authored or newly-versioned skills onto this agent.

        Call this after you've finished writing all the files for a new
        skill (SKILL.md + module + tests/smoke_test.py). The loader runs
        each skill's smoke test before activation; a failing test means
        the skill is NOT registered and you must fix the skill (not the
        test) before retrying. Returns the names of skills newly
        registered this call."""
        from jaeger_os.core.skills.skill_loader import load_and_register, _REGISTERED_KEYS
        cfg = _pipeline["config"]
        before = {(n, v, z) for (n, v, z) in _REGISTERED_KEYS}
        # Phase-9 sentinel: ``load_and_register`` only needs an object
        # whose ``tool_plain`` is callable (it mirrors registrations
        # through the global tool registry). The legacy ``agent``
        # symbol from the pre-Phase-9 closure no longer exists in this
        # scope — passing a fresh sentinel keeps the call working
        # without re-introducing pydantic-ai's Agent dependency.
        report = load_and_register(
            _RegistrationSentinel(),
            _pipeline["layout"],
            run_smoke_tests=cfg.skills.run_smoke_tests,
            enabled_allowlist=list(cfg.skills.enabled_base_skills) or None,
            audit=lambda ev, payload: jaeger_tools._audit(ev, payload),
        )
        after = set(_REGISTERED_KEYS)
        newly = sorted(after - before)
        return {
            "newly_registered": [
                {"name": n, "version": v, "zone": z} for (n, v, z) in newly
            ],
            "skipped": [
                {"name": s.name, "version": s.version, "zone": s.zone, "reason": reason[:200]}
                for (s, reason) in report.skipped
            ],
            "total_registered": len(after),
        }

    @register_tool_from_function
    def list_plugins() -> dict:
        """Enumerate the bundled jaeger_os plugins (discord, telegram,
        imessage, whisper_stt, kokoro_tts, mcp) with install + credential
        status for each. Use this when the user asks what integrations
        are available, or before suggesting a feature you'd need a
        plugin for."""
        return t.list_plugins()

    @register_tool_from_function
    def setup_plugin(name: str) -> dict:
        """Return step-by-step setup instructions for the named plugin
        (e.g. ``discord``, ``telegram``, ``whisper_stt``). Surfaces
        missing libraries to ``pip install`` and required env vars or
        credentials that need values. Does NOT modify the user's
        environment — the user runs the install commands and stores
        credentials themselves."""
        return t.setup_plugin(name=name)

    @register_tool_from_function
    def listen(seconds: int = 5) -> dict:
        """Record N seconds of microphone audio and return the transcript.

        Use when the user asks you to listen, or when you need to capture
        spoken input mid-chat. Atomic: mic opens, records, closes — no
        always-on listening. Cap is 60s; for hands-free conversation, tell
        the user to launch ``python -m jaeger_os --voice`` instead.

        Returns ``{ok, transcript, seconds, model, elapsed_s}`` on success."""
        return t.listen(seconds=seconds)


# ---------------------------------------------------------------------------
# Sub-agent delegate — recursive invocation with depth guard
# ---------------------------------------------------------------------------
_DELEGATE_MAX_DEPTH = int(os.environ.get("DELEGATE_MAX_DEPTH", "2"))
_delegate_depth = threading.local()


def _delegate_internal(client: Any, subtask: str) -> dict[str, Any]:
    """Run a subtask through the same agent loop with a fresh history.

    Same pattern python_pydantic_ai uses: bumps a thread-local depth
    counter, runs the subtask, returns the answer + elapsed time.
    Depth-limited to prevent runaway recursion if a sub-agent decides
    to delegate again.
    """
    depth = getattr(_delegate_depth, "value", 0)
    if depth >= _DELEGATE_MAX_DEPTH:
        return {
            "delegated": False,
            "error": f"delegate recursion limit hit ({_DELEGATE_MAX_DEPTH}); "
                     "the sub-agent tried to delegate again — refusing.",
        }
    clean = (subtask or "").strip()
    if not clean:
        return {"delegated": False, "error": "empty subtask"}

    _delegate_depth.value = depth + 1
    started = time.perf_counter()
    try:
        # Phase-6.2 cutover: delegate now drives the new JaegerAgent
        # loop. A fresh ``JaegerAgent`` per subtask keeps history scoped
        # to the delegate's work (a child agent doesn't inherit the
        # parent's context — the spec calls this out).
        from jaeger_os.agent.loop.runtime_bridge import build_jaeger_agent, drive_one_turn
        _cfg = _pipeline.get("config")
        _ctx = getattr(getattr(_cfg, "model", None), "ctx", None)
        sub_agent = build_jaeger_agent(
            client,
            system_prompt=_pipeline["system_prompt"],
            toolsets=_pipeline.get("toolsets"),
            skip_final_tools=SKIP_FINAL_TOOLS,
            ctx_window=_ctx,
        )
        lock = _pipeline.get("llm_lock")
        if lock is not None:
            with lock:
                iter_out = drive_one_turn(sub_agent, clean)
        else:
            iter_out = drive_one_turn(sub_agent, clean)
    except Exception as exc:
        _delegate_depth.value = depth
        return {"delegated": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _delegate_depth.value = depth

    elapsed = time.perf_counter() - started
    # ``drive_one_turn`` returns a shape that includes ``answer``,
    # ``skipped``, ``tool_activity``, etc.  Translate to the legacy
    # ``iter_out`` keys the surrounding code below expects.
    # ``drive_one_turn`` already populates ``answer`` for both the
    # skip-final shortcut and the full loop path — no separate result
    # object to interrogate.
    answer = iter_out.get("answer") or ""
    return {
        "delegated": True,
        "subtask": clean,
        "answer": str(answer).strip(),
        "depth": depth + 1,
        "elapsed_s": round(elapsed, 3),
    }


# Hard cap on concurrent subagents. The robot is memory-bound — all
# subagents share the ONE loaded Gemma model (no second model load),
# and llama-cpp serializes decode, so 2 is the practical ceiling.
# For sustained background work prefer Deep Think (sequential queue +
# model swap) over fanning out parallel subagents.
_MAX_PARALLEL_SUBAGENTS = 2


def _delegate_parallel(client: Any, subtasks: list[str]) -> dict[str, Any]:
    """Fan a small set of subtasks out across up to
    :data:`_MAX_PARALLEL_SUBAGENTS` worker threads.

    All subagents share the one loaded Gemma model. llama-cpp can't
    decode two prompts at once, so each subagent's model access
    serializes through ``_pipeline['llm_lock']`` — the win here is
    orchestration (queue N, collect all answers) plus overlap on
    non-LLM tool work, NOT raw decode speedup. For sustained
    background work, Deep Think is the better mechanism.

    More than the cap of subtasks is allowed — the thread pool runs
    the cap at a time and queues the rest. Returns one result entry
    per subtask, in input order."""
    from concurrent.futures import ThreadPoolExecutor

    clean = [s.strip() for s in (subtasks or []) if s and s.strip()]
    if not clean:
        return {"ok": False, "error": "no subtasks given"}

    parent_depth = getattr(_delegate_depth, "value", 0)
    if parent_depth >= _DELEGATE_MAX_DEPTH:
        return {
            "ok": False,
            "error": f"delegate recursion limit hit ({_DELEGATE_MAX_DEPTH})",
        }

    def _worker(task: str) -> dict[str, Any]:
        # Worker runs on a fresh thread — _delegate_depth is
        # thread-local, so seed it here to keep nested delegation
        # bounded.
        _delegate_depth.value = parent_depth + 1
        try:
            return _delegate_internal(client, task)
        finally:
            _delegate_depth.value = parent_depth

    started = time.perf_counter()
    with ThreadPoolExecutor(
        max_workers=_MAX_PARALLEL_SUBAGENTS,
        thread_name_prefix="subagent",
    ) as pool:
        results = list(pool.map(_worker, clean))
    elapsed = time.perf_counter() - started

    succeeded = sum(1 for r in results if r.get("delegated"))
    return {
        "ok": True,
        "subtask_count": len(clean),
        "max_concurrent": _MAX_PARALLEL_SUBAGENTS,
        "succeeded": succeeded,
        "failed": len(clean) - succeeded,
        "results": results,
        "elapsed_s": round(elapsed, 3),
    }




# ---------------------------------------------------------------------------
# agent.iter() drive loop with skip-final intercept
# ---------------------------------------------------------------------------
_FAST_FINALIZE_DIRECTIVE = (
    "You just called the `{tool}` tool. The tool returned:\n"
    "{result}\n\n"
    "Reply to the user's original question in ONE short, natural sentence "
    "using that result. Do NOT call any more tools. Plain text only."
)

_DETERMINISTIC_FINAL_TOOLS = frozenset({
    "get_time", "calculate", "list_facts", "recall", "remember", "forget",
    "delete_file", "list_credentials", "schedule_prompt", "cancel_schedule",
    "reload_skills", "listen", "board_add", "board_move", "board_update",
})


def _fast_finalize_sync(
    client: Any,
    user_text: str,
    tool_name: str,
    tool_result: Any,
    *,
    max_tokens: int = 120,
) -> str:
    """Bounded single-shot LLM call that turns a tool result into a
    one-sentence user-facing answer.

    The "skip-final" tools used to bypass the LLM entirely — fast, but
    the user saw raw dicts ("2026-05-19 04:50:09 PM PDT") instead of
    conversational answers ("It's 4:50 PM"). This helper keeps the LLM
    IN the loop on those turns while capping token count + temperature
    so the cost stays close to the original bypass (~0.3-0.7s vs
    ~1.5-2s for an unconstrained finalize). Falls back to the raw
    formatter on any client/model failure."""
    formatted = _format_tool_result_as_answer(tool_name, tool_result)
    # Nothing to finalize — e.g. text_to_speech: the audio IS the output,
    # so the formatted answer is empty. Running the LLM on an empty
    # result makes it HALLUCINATE a fresh answer (a different joke than
    # the one just spoken). Return the empty/short answer directly.
    if not formatted.strip():
        return formatted
    # Deterministic/simple tools: the formatted result is already the
    # answer. Skipping the final LLM pass improves latency and prevents
    # result-grounding hallucinations (notably memory/list tools).
    if tool_name in _DETERMINISTIC_FINAL_TOOLS or tool_name == "text_to_speech":
        return formatted
    if client is None:
        return formatted
    system = _pipeline.get("system_prompt") or ""
    directive = _FAST_FINALIZE_DIRECTIVE.format(tool=tool_name, result=formatted)
    try:
        result = client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
                {"role": "user", "content": directive},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
            top_p=0.9,
            stream=False,
            # Carry the decide call's tool schemas so this finalize
            # renders the identical <system + tools> prefix and reuses
            # the warm KV instead of evicting it.
            tools=_pipeline.get("openai_tools"),
        )
        text = (getattr(result, "text", None) or "").strip()
        # Strip any drift tool-call markup the model leaked into the
        # final-text response (e.g. Gemma emitting
        # ``<|tool_call>call:recall(key='x')<tool_call|>`` mid-text).
        # Without this, the user sees raw markup; with it, we surface
        # just the prose. NB: we don't try to EXECUTE the leaked tool
        # call here — that'd require another agent.iter pass and we're
        # already in the fast-finalize fast path. The multi-step
        # detector upstream is what gives the model a chance to chain.
        text = _strip_drift_markup(text)
        return text or formatted
    except Exception:
        return formatted


def _strip_drift_markup(text: str) -> str:
    """Remove any of the four drift tool-call markup patterns from
    ``text`` and return what's left. Lazy import of the patterns so the
    bench / non-LLM call paths don't pay the cost."""
    if not text or "<" not in text:
        return text
    # Use the agent layer's drift parser to strip tool-call envelopes
    # from text we'd otherwise show to the user (TUI banner, finalize
    # fallback). The parser knows the same patterns as the adapters.
    from jaeger_os.agent.dialects import _DRIFT_PATTERNS  # noqa: PLC2701
    cleaned = text
    for pattern in _DRIFT_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


# Imperative verbs that strongly imply a tool call. Used in two-pass
# detection: count how many distinct imperatives appear in the prompt.
_IMPERATIVE_VERBS = (
    r"run|read|write|save|delete|append|cancel|list|tell|recall|"
    r"remember|forget|fetch|search|speak|narrate|create|make|open|"
    r"launch|use|call|verify|confirm|reload|schedule|calculate|"
    r"compute|count|show|find|look\s*up|check|store|set|build|"
    # Edit-intent verbs — "finish the code", "fix the file" are
    # implicitly read-then-write tasks. Including them here lets the
    # two-verb counter trip multi-step for prompts like "fix and run".
    r"finish|complete|fix|implement|edit|update|modify|improve|"
    r"rewrite|refactor|debug|correct"
)
# Sequential connectors that explicitly indicate "this is the next step".
# Allows optional adverbs between the connector and the verb, e.g.
# "then immediately recall" or "and then quickly run".
_CONNECTOR_THEN_VERB = re.compile(
    rf"\b(?:then|and(?:\s+then)?|after\s+(?:that|writing|creating|saving|"
    rf"running|reading|fetching)|next,?|finally,?)\s+(?:\w+\s+){{0,2}}"
    rf"(?:{_IMPERATIVE_VERBS})\b",
    re.IGNORECASE,
)
# Direct imperative-verb count — three or more in one prompt is also
# a strong "multi-step" signal even without explicit connectors
# ("write fib.py and run it" has both "write" and "run").
_VERB_COUNTER = re.compile(rf"\b({_IMPERATIVE_VERBS})\b", re.IGNORECASE)


def _looks_multistep(user_text: str) -> bool:
    """Return True when the user's prompt looks like it needs more than
    one tool call. Two checks:
      1. Explicit sequential connectors ("then run", "after writing")
      2. Two or more distinct imperative verbs ("write fib.py and run it")

    When this fires, ``_run_via_iter`` suppresses the skip-final
    shortcut so agent.iter runs the full loop and the model can chain
    into the next tool naturally. Skip-final is great for single-shot
    questions but actively breaks multi-step requests."""
    if not user_text:
        return False
    if _CONNECTOR_THEN_VERB.search(user_text):
        return True
    verbs = {m.group(1).lower() for m in _VERB_COUNTER.finditer(user_text)}
    return len(verbs) >= 2


# --- P4: loop backstop -------------------------------------------------------
# A turn must terminate. These guard a model that spins tool calls without
# making progress: a hard ceiling on total calls, and a tight-loop catcher
# for the exact same (tool, args) issued over and over. Observed legitimate
# multi-step work tops out near ~16 calls and varies its arguments, so
# neither limit trips on a healthy turn — they are a safety net, not a
# fine-grained iteration tuner.


def begin_turn_cancel_scope() -> "threading.Event":
    """Open a fresh cancellation scope for one turn and return its Event.

    Set the Event from any thread — the REPL on Ctrl-C, or the voice
    layer when the user speaks — to ask the in-flight turn to stop. The
    agent loop (:func:`_run_via_iter`) checks it between steps and halts
    gracefully. Cleared here so a stale cancel can't kill the next turn.

    The Event comes from :mod:`jaeger_os.core.runtime.tool_interrupt` so it is the
    *same* object a long-running tool polls via ``is_interrupted()`` — one
    cancel flag, checked between loop nodes *and* mid-tool."""
    ev = tool_interrupt.begin_scope()
    _pipeline["cancel_event"] = ev
    return ev


def request_turn_cancel() -> None:
    """Ask the in-flight turn to stop. No-op when no turn scope is open."""
    ev = _pipeline.get("cancel_event")
    if ev is not None:
        ev.set()
    agent = _pipeline.get("active_jaeger_agent")
    if agent is not None and hasattr(agent, "interrupt"):
        try:
            agent.interrupt()
        except Exception:  # noqa: BLE001 — cancel must be best-effort
            pass


# Per-(client, system_prompt, mcp_specs) cache so a single set of skill
# registrations + smoke tests doesn't re-run on every turn. The value is
# the ``_RegistrationSentinel`` returned by ``_get_agent``; the cache
# clears whenever the model is hot-swapped (see ``/model`` slash command).
_agent_cache: dict[tuple, Any] = {}


def _agent_key(client: Any) -> tuple:
    mcp_fingerprint = tuple(sorted(
        getattr(s, "qualified_name", "") for s in _pipeline.get("mcp_specs") or []
    ))
    return (id(client), hash(_pipeline["system_prompt"]), mcp_fingerprint)


class _RegistrationSentinel:
    """Stand-in passed to the skill loader where the legacy pydantic-ai
    ``Agent`` used to live. The loader's ``_ToolCapturingAgent`` only
    needs ``tool_plain`` / ``tool`` to be *callable*; everything else
    falls through ``__getattr__`` and skill code shouldn't read it —
    we keep the attribute pass-through as a no-op so a stray
    ``agent.something`` lookup returns a harmless lambda rather than
    crashing the load."""

    def __getattr__(self, name: str) -> Any:  # noqa: D401
        return lambda *a, **k: None


def _get_agent(client: Any) -> object:
    """Cached registration trigger — calls ``_register_builtins`` +
    the skill loader once per ``(client, system_prompt, mcp_specs)``
    fingerprint and returns the sentinel.

    Phase-9 cleanup: no pydantic-ai ``Agent`` is constructed any more.
    Tools live in :mod:`jaeger_os.agent.schemas.tool_registry`; the sentinel
    exists only so the skill loader's ``_ToolCapturingAgent`` wrapper
    has something to wrap.
    """
    key = _agent_key(client)
    if key not in _agent_cache:
        _agent_cache.clear()
        _register_builtins(client)
        sentinel = _RegistrationSentinel()
        # Skill loader registers base + instance skills AFTER built-ins,
        # so an instance skill named `get_time_v2` overrides the built-in
        # (last-write-wins in the registry).
        load_and_register(
            sentinel,
            _pipeline["layout"],
            run_smoke_tests=_pipeline["config"].skills.run_smoke_tests,
            enabled_allowlist=list(_pipeline["config"].skills.enabled_base_skills) or None,
            audit=lambda ev, payload: jaeger_tools._audit(ev, payload),
        )
        _agent_cache[key] = sentinel
    return _agent_cache[key]


def prewarm(client: Any) -> None:
    """Prime the KV cache so the first user-facing turn isn't cold.

    The first agent call against a freshly-loaded model pays a ~1 s
    prefill cost to tokenize the (long) v2 system prompt + the tool
    schema. By running a single trivial turn at startup, we shift that
    cost from "what time is it" to the load phase — where the user
    already accepts a wait. Idempotent. Mirrors python_pydantic_ai.prewarm.
    """
    if _pipeline.get("prewarmed"):
        return
    # External models have no local KV cache to prime — and make_client
    # already ran a live connectivity check. Skip the extra API round.
    if getattr(client, "kind", "local") == "external":
        _pipeline["prewarmed"] = True
        return
    started = time.perf_counter()
    try:
        # Phase-8 fix: prewarm hits the raw client.chat directly instead
        # of going through the full JaegerAgent loop. The full loop
        # renders all registered tool schemas (~9K tokens) which is a
        # 20-30s prefill on a cold model — long enough to trip the
        # stale-call detector and abandon the worker thread, which
        # corrupts llama-cpp's KV cache and breaks the FIRST real turn
        # with ``llama_decode -3``. The lightweight version below
        # primes the cache safely without the tool surface.
        _get_agent(client)  # still wires the tool registry + skills
        llama = getattr(client, "llm", None)
        if llama is not None and hasattr(llama, "create_chat_completion"):
            # In-process llama-cpp path. Use ONE-token max + no tools so
            # the prefill is bounded.
            llama.create_chat_completion(
                messages=[
                    {"role": "system", "content": _pipeline["system_prompt"]},
                    {"role": "user", "content": "ready"},
                ],
                max_tokens=1,
                temperature=0.0,
            )
        else:
            # HTTP-backed external client — the connectivity check
            # already covered the cold-start. Nothing to do here.
            pass
    except Exception as exc:
        print(f"[jaeger] prewarm skipped: {exc}", flush=True)
        return
    _pipeline["prewarmed"] = True
    print(f"[jaeger] agent prewarmed in {time.perf_counter() - started:.1f}s", flush=True)


def warm_plugins(config: Any) -> None:
    """Boot-time plugin warmup — per ``config.warmup``, pre-load TTS /
    STT / vision so the Jaeger is fully operational the instant boot
    finishes, not on first use. Each warm is timed and best-effort: a
    failure prints a warning and never blocks boot. Robots run TTS/STT
    constantly, so those default on (see :class:`WarmupConfig`)."""
    w = getattr(config, "warmup", None)
    if w is None:
        return
    jobs: list[tuple[str, Any]] = []
    if getattr(w, "tts", False):
        from .core.tools.speak import warm_kokoro
        jobs.append(("TTS (Kokoro)", warm_kokoro))
    if getattr(w, "stt", False):
        from .core.tools.listen import warm_listen
        jobs.append(("STT (Whisper)", warm_listen))
    if getattr(w, "vision", False):
        from .core.tools.vision import warm_vision
        jobs.append(("vision (Moondream2)", warm_vision))
    for name, fn in jobs:
        started = time.perf_counter()
        try:
            fn()
            print(f"[jaeger] warmed {name} in "
                  f"{time.perf_counter() - started:.1f}s", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[jaeger] warm {name} skipped: "
                  f"{type(exc).__name__}: {exc}", flush=True)


def _confirmation_provider(config: Any, layout: Any = None) -> Any:
    """Pick the permission confirmation provider for ``config``.

    'confirm' mode → the interactive console prompt. 'allow' mode →
    auto-approve (a trusted, unattended robot). The mode is chosen at
    first-boot setup and persisted in config.yaml, so the posture
    survives every restart. The TUI swaps in its own spinner-aware
    prompt for 'confirm' mode (see ``_install_confirmations``).

    ``layout`` supplies the instance dir so the console provider can
    load + persist per-skill grants (``<instance>/permissions.json``)."""
    mode = getattr(getattr(config, "permissions", None), "mode", "confirm")
    if mode == "allow":
        from jaeger_os.core.safety.permissions import AllowAllProvider
        return AllowAllProvider()
    return ConsoleConfirmationProvider(instance_dir=getattr(layout, "root", None))


def _preflight_log() -> None:
    """Run the environment preflight and print a concise warning block
    if an optional dependency or system library is missing. Silent when
    everything is ready. Best-effort — preflight never blocks boot."""
    try:
        from jaeger_os.core.runtime.preflight import boot_warning, check_environment
        warning = boot_warning(check_environment())
        if warning:
            print(warning, flush=True)
    except Exception:  # noqa: BLE001
        pass


# Phase-6 migration: per-session ``JaegerAgent`` instances live here
# while the new path is opt-in. Keyed by session so multi-turn context
# accumulates the same way the legacy pydantic-ai history dict does.
_jaeger_agents_by_session: dict[str, Any] = {}


def _run_turn_via_jaeger_agent(
    client: Any,
    user_text: str,
    *,
    session_key: str,
) -> dict[str, Any]:
    """Phase-6 parallel implementation of :func:`_run_turn` that drives
    the loop through :class:`JaegerAgent`. Returns the exact same dict
    shape so ``run_command`` / ``run_for_voice`` don't need to know
    which loop ran."""
    from jaeger_os.agent.loop.runtime_bridge import build_jaeger_agent, drive_one_turn

    key = session_key
    # First call per session builds + caches a JaegerAgent. Force the
    # pydantic-ai agent to build too so its tool registrations + the
    # bridge's mirror both fire.
    if key not in _jaeger_agents_by_session:
        _get_agent(client)  # populates the new registry via _get_agent's mirror
        from .agent import AgentCallbacks
        # Per-turn tool-time accumulator. The latency log was reporting
        # ``tool=0.0`` even when tools were the dominant cost; now we
        # sum the ``done`` event's ``elapsed_s`` so the report has the
        # one breakdown number we can actually capture without adapter
        # cooperation. ``_pipeline['turn_tool_time']`` is reset at the
        # start of every turn (just before ``drive_one_turn``) and read
        # immediately after.
        _pipeline.setdefault("turn_tool_time", 0.0)

        def _tool_progress(name: str, phase: str, data: Any) -> None:
            if phase == "start":
                set_agent_status("tool", detail=name)
            else:
                set_agent_status("thinking", detail="")
                if phase == "done" and isinstance(data, dict):
                    try:
                        _pipeline["turn_tool_time"] = (
                            _pipeline.get("turn_tool_time", 0.0)
                            + float(data.get("elapsed_s", 0.0) or 0.0)
                        )
                    except (TypeError, ValueError):
                        pass
            # Daemon-mode: forward to any chat.subscribe subscribers
            # so a remote TUI / attach client shows live tool activity.
            # In-process boot (no daemon) leaves the bus unset and
            # this is a no-op.
            bus = _pipeline.get("daemon_event_bus")
            if bus is not None:
                try:
                    payload: dict[str, Any] = {"name": name, "phase": phase}
                    if isinstance(data, dict):
                        # Only ship JSON-able scalars; the full data
                        # dict can hold non-serializable references.
                        for k in ("elapsed_s", "args_preview", "result_preview"):
                            if k in data:
                                payload[k] = data[k]
                    bus.publish("tool.progress", **payload)
                except Exception:  # noqa: BLE001 — never let pub break the agent
                    pass

        # DB-6: persist a tool_calls audit row per dispatch. Best-effort
        # — record_tool_call swallows DB failures so a SQL hiccup never
        # crashes a turn. Session key is captured by closure from the
        # outer ``key`` binding.
        def _tool_done(
            name: str,
            args: dict[str, Any],
            result: Any,
            ok: bool,
            error: str | None,
            elapsed_s: float,
        ) -> None:
            try:
                mem.record_tool_call(
                    session_key=key,
                    tool_name=name,
                    args=args,
                    result=result,
                    ok=ok,
                    error=error,
                    elapsed_s=elapsed_s,
                )
            except Exception:  # noqa: BLE001 — observer must never break the turn
                pass

        def _heartbeat(elapsed_s: float) -> None:
            # Keep the status line honest while the first model call is
            # still pre-filling/decoding and no tool has fired yet.
            # Preserve since_ts so the visible elapsed timer reflects
            # the whole model wait, not the most recent heartbeat.
            snap = get_agent_status()
            since_ts = (
                float(snap.get("since_ts") or 0.0)
                if snap.get("state") == "thinking"
                else 0.0
            )
            set_agent_status(
                "thinking",
                detail=f"waiting on model {elapsed_s:.1f}s",
                since_ts=since_ts or time.time(),
            )

        _status_cb = AgentCallbacks(
            tool_progress=_tool_progress,
            tool_done=_tool_done,
            heartbeat=_heartbeat,
        )
        # Pipe the configured ctx window into the agent's pre-flight
        # ContextGuard so an oversized prompt is trimmed (or refused)
        # before the server sees it. See docs/context_guard.md.
        _cfg = _pipeline.get("config")
        _ctx = getattr(getattr(_cfg, "model", None), "ctx", None)
        # Oversized tool results land under <instance>/logs/tool_results/
        # so the model can read the full body with read_file if the
        # in-prompt preview wasn't enough. Falls back to truncate-only
        # when no layout is bound (shouldn't happen in real boot).
        _layout = _pipeline.get("layout")
        _artifact_dir = (
            (_layout.logs_dir / "tool_results") if _layout is not None else None
        )
        # Stall watchdog — caller-controlled via ``model.stall_timeout_s``
        # in config.yaml. ``None`` lets ``build_jaeger_agent`` pick a
        # backend-appropriate default (120s for in-process, 30s for HTTP).
        _stall_s = getattr(getattr(_cfg, "model", None), "stall_timeout_s", None)
        _jaeger_agents_by_session[key] = build_jaeger_agent(
            client,
            system_prompt=_pipeline["system_prompt"],
            toolsets=_pipeline.get("toolsets"),
            skip_final_tools=SKIP_FINAL_TOOLS,
            callbacks=_status_cb,
            ctx_window=_ctx,
            artifact_dir=_artifact_dir,
            stale_call_timeout_s=_stall_s,
        )
    jaeger_agent = _jaeger_agents_by_session[key]

    lock = _pipeline["llm_lock"]
    started = time.perf_counter()
    set_agent_status("thinking", detail="")
    # Reset the per-turn tool-time accumulator before the dispatch so
    # cross-turn leakage doesn't inflate this turn's report.
    _pipeline["turn_tool_time"] = 0.0
    try:
        _pipeline["active_jaeger_agent"] = jaeger_agent
        if lock is not None:
            with lock:
                result = drive_one_turn(jaeger_agent, user_text)
        else:
            result = drive_one_turn(jaeger_agent, user_text)
    except Exception as exc:  # noqa: BLE001 — match legacy crash surface
        elapsed = time.perf_counter() - started
        report = LatencyReport(elapsed, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
        write_log({
            "user": user_text, "session_key": key, "error": str(exc),
            "latency": asdict(report), "framework_path": "jaeger_os_agent",
        })
        set_agent_status("error", detail=f"{type(exc).__name__}")
        return {"text": "", "error": str(exc), "tool_activity": [],
                "first_decision": None, "skipped_final": False,
                "spoke_via_tool": False, "elapsed_s": elapsed, "report": report}
    finally:
        if _pipeline.get("active_jaeger_agent") is jaeger_agent:
            _pipeline["active_jaeger_agent"] = None

    answer = (result["answer"] or "").strip()
    tool_activity = result["tool_activity"]
    first_decision = result["first_decision"]
    elapsed = result["elapsed_s"]
    skipped = result["skipped"]

    # Tool time we can fill — summed from the ``tool_progress("done")``
    # callback via the per-turn accumulator. ``decision`` / ``final``
    # still need adapter cooperation (per-call ``last_call_times``);
    # they're a follow-up in the adapter layer (Phase 7 item).
    _tool_time = float(_pipeline.get("turn_tool_time", 0.0) or 0.0)
    # Loop time is whatever's left after the tools — adapter + parse +
    # dispatch bookkeeping. Not the model's per-phase breakdown, but
    # enough to spot a turn where the tools dominate vs the model.
    _loop_time = max(0.0, elapsed - _tool_time)
    report = LatencyReport(
        total=elapsed,
        tool_calls=len(tool_activity),
        decision=_loop_time, decision_ttft=0.0,
        tool=_tool_time, final=0.0, final_ttft=0.0,
    )

    write_log({
        "user": user_text, "session_key": key, "answer": answer,
        "tool_calls": len(tool_activity), "tool_activity": tool_activity,
        "decision": first_decision, "skipped_final": skipped,
        "latency": asdict(report),
        "iterations": result["iterations"],
        "halt_reason": result["halt_reason"],
        "framework_path": "jaeger_os_agent",
    })

    # Trim per-session message history at the legacy limit so an
    # apples-to-apples L3 multi-turn bench measures the same memory
    # window. The factor of two accounts for tool-result pairs that
    # the legacy path counted as one slot.
    overflow = len(jaeger_agent.messages) - _MAX_HISTORY_MESSAGES * 2
    if overflow > 0:
        del jaeger_agent.messages[:overflow]

    runner = _pipeline["thinking_runner"]
    if runner is not None:
        runner.queue(user_text, run_id=os.environ.get("BENCH_RUN_ID"))

    set_agent_status("ready")
    # ``spoke_via_tool`` tells the voice loop "the model already spoke
    # the answer through ``text_to_speech`` — don't re-speak the
    # returned text". Previously this checked for a ``🔊`` emoji in
    # the activity lines, but the Phase-9 renderer
    # (:func:`_tool_activity_lines`) emits ``  ▸ tool(args)`` with no
    # emoji, so the check was always False → every voice turn that
    # used ``text_to_speech`` played the audio TWICE (once from the
    # tool, once from the TUI's post-turn ``v.speak(text)`` fallback).
    # Now we check by tool name AND fall back to the legacy emoji
    # marker for any caller still on the older formatter.
    _SPOKEN_TOOLS = ("text_to_speech", "speak")
    spoke_via_tool = any(
        "🔊" in line
        or any(f"▸ {t}(" in line for t in _SPOKEN_TOOLS)
        for line in tool_activity
    )
    return {
        "text": answer, "error": None, "tool_activity": tool_activity,
        "first_decision": first_decision, "skipped_final": skipped,
        "spoke_via_tool": spoke_via_tool,
        "elapsed_s": elapsed, "report": report,
    }


def _run_turn(client: Any, user_text: str, *, session_key: str) -> dict[str, Any]:
    """The unified agent turn — the one path every entry point shares.

    Runs the loop, extracts the answer + tool activity, writes the log,
    updates session memory, and returns a structured result dict.
    ``run_command`` and ``run_for_voice`` are thin output adapters over
    this — see them below. Never prints; never raises.

    Phase-6.2 cutover: the loop is now ``JaegerAgent`` unconditionally.
    The legacy pydantic-ai code paths below the early-return are
    unreachable and will be deleted in the next cleanup pass."""
    return _run_turn_via_jaeger_agent(client, user_text, session_key=session_key)


def run_command(client: Any, user_text: str, session_key: str | None = None) -> None:
    """Run a turn and print the answer + tool activity to stdout.
    Thin output adapter over :func:`_run_turn` — used by the one-shot
    CLI, the cron runner, and the daemon."""
    out = _run_turn(client, user_text,
                    session_key=session_key or _DEFAULT_SESSION_KEY)
    if out["error"]:
        print(f"Jaeger agent failed: {out['error']}")
        if _pipeline.get("show_latency"):
            print_latency(out["report"])
        return
    if _pipeline.get("show_tool_activity", True):
        for line in out["tool_activity"]:
            print(line)
    if out["text"]:
        print(out["text"])
    if _pipeline.get("show_latency"):
        print_latency(out["report"])
        if out["skipped_final"]:
            print("  (final-LLM skipped — tool result returned directly)")


def run_for_voice(client: Any, user_text: str, session_key: str | None = None) -> dict[str, Any]:
    """Run a turn and return a structured dict instead of printing.
    Thin output adapter over :func:`_run_turn` — used by the TUI voice
    path and the messaging bridges (which pass channel-specific
    session_keys like "telegram:12345" so each chat keeps its context)."""
    out = _run_turn(client, user_text, session_key=session_key or "voice")
    return {
        "text": out["text"], "tool_activity": out["tool_activity"],
        "spoke_via_tool": out["spoke_via_tool"], "elapsed_s": out["elapsed_s"],
        "skipped_final": out["skipped_final"], "error": out["error"],
    }


def init_extensions(args: Any, client: Any) -> None:
    """Wire up memory / MCP / thinking based on CLI flags + env vars.
    Mirrors python_pydantic_ai.init_extensions."""
    with_memory = getattr(args, "with_memory", False) or os.environ.get("JAEGER_WITH_MEMORY") == "1"
    with_mcp = getattr(args, "with_mcp", False) or os.environ.get("JAEGER_WITH_MCP") == "1"
    with_thinking = getattr(args, "think", False) or os.environ.get("JAEGER_WITH_THINKING") == "1"

    _pipeline["with_memory"] = with_memory
    _pipeline["with_mcp"] = with_mcp
    _pipeline["with_thinking"] = with_thinking
    _pipeline["client"] = client

    if with_mcp:
        try:
            from .plugins.mcp import client as mcp_client
            registry = mcp_client.init_from_config()
            specs = registry.list_tools()
            _pipeline["mcp_specs"] = specs
            if specs:
                print(f"[jaeger] MCP enabled with {len(specs)} extended tool(s).", flush=True)
        except Exception as exc:
            print(f"[jaeger] --with-mcp failed: {exc}", file=sys.stderr, flush=True)

    if with_thinking:
        try:
            from .core.runners import thinking_runner
            lock = _pipeline.get("llm_lock") or threading.Lock()
            _pipeline["llm_lock"] = lock
            # Per-instance log path keeps thinking output out of the framework
            # source tree (matches the vocabulary contract — runners log into
            # <instance>/logs/, not into core/).
            layout = _pipeline.get("layout")
            log_path = (layout.logs_dir / "thinking.jsonl") if layout is not None else None
            _pipeline["thinking_runner"] = thinking_runner.ThinkingRunner(
                client, "jaeger_os", lock, _pipeline["system_prompt"],
                log_path=log_path,
            )
            print("[jaeger] background thinking enabled — see <instance>/logs/thinking.jsonl.", flush=True)
        except Exception as exc:
            print(f"[jaeger] --think failed: {exc}", file=sys.stderr, flush=True)


def shutdown_extensions(wait: bool = True) -> None:
    """Drain any background thinking jobs before tear-down."""
    runner = _pipeline["thinking_runner"]
    if runner is not None:
        if runner.pending() > 0:
            print("[jaeger] waiting for background thinking jobs...", flush=True)
        runner.shutdown(wait=wait)


# ---------------------------------------------------------------------------
# Llama-cpp-python client shim
# ---------------------------------------------------------------------------
@dataclass
class _ChatResult:
    """Minimal completion shape ThinkingRunner expects."""
    text: str
    latency_s: float
    ttft_s: float = 0.0



class LlamaCppPythonClient:
    """Loads a Llama instance once and exposes ``.llm`` (the raw
    ``llama_cpp.Llama`` instance) plus ``.chat()`` for the bounded
    finalize / fast-finalize passes.

    This is the local-first default brain. The opt-in alternative is
    :class:`jaeger_os.core.models.external_model.ExternalModelClient`, which
    presents the same ``.chat()`` / ``.kind`` surface. The new agent
    loop (Phase-9) wraps ``.llm`` in
    :class:`jaeger_os.agent.LocalLlamaAdapter` to drive inference;
    nothing here talks to ``pydantic-ai`` any more."""

    kind = "local"

    def describe(self) -> str:
        return f"local · llama-cpp · {getattr(self, 'model_name', '?')}"

    def __init__(self, model_cfg: Any, warmup: bool = True) -> None:
        from llama_cpp import Llama

        from jaeger_os.core.models.model_resolver import resolve_model_path
        # Resolve through the registry so configs can carry a stable
        # name like "gemma-4-26b-a4b-it-q4_k_m" instead of a fragile
        # absolute path. Downloads from HF Hub on first use if the
        # file isn't in ~/.jaeger/models/ or ./models/.
        resolved = resolve_model_path(model_cfg.model_path)
        path = Path(resolved)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")
        self.model_name = path.name
        kwargs: dict[str, Any] = {
            "model_path": str(path),
            "n_ctx": model_cfg.ctx,
            "n_gpu_layers": model_cfg.gpu_layers,
            "n_batch": model_cfg.n_batch,
            "n_ubatch": model_cfg.n_ubatch,
            "flash_attn": model_cfg.flash_attn,
            "verbose": False,
        }
        if model_cfg.threads is not None:
            kwargs["n_threads"] = model_cfg.threads
        print(f"[jaeger] loading {path.name}...", flush=True)
        started = time.perf_counter()
        self.llm = Llama(**kwargs)
        print(f"[jaeger] loaded in {time.perf_counter() - started:.1f}s.", flush=True)
        if warmup:
            self.llm.create_chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1, temperature=0.0,
            )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        top_p: float = 0.95,
        stream: bool = False,
        grammar: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> _ChatResult:
        """Minimal chat completion wrapper (ThinkingRunner, _fast_finalize).
        Ignores `stream` and `grammar`. Returns text + wall-clock latency.

        Pass ``tools`` to render the SAME ``<system + tools>`` prompt
        prefix the agent's decide call uses — that keeps the tool-schema
        KV cache resident across decide/finalize instead of evicting it
        (a system-only finalize forces the next decide to cold-prefill
        all ~60 tool schemas, ~12s)."""
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "top_p": top_p, "stream": False,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        completion = self.llm.create_chat_completion(**kwargs)
        elapsed = time.perf_counter() - started
        text = completion["choices"][0]["message"].get("content") or ""
        return _ChatResult(text=text.strip(), latency_s=elapsed)


def make_client(config: Any, layout: Any = None, *, warmup: bool = True) -> Any:
    """Build the agent's brain client for ``config``.

    Local-first: returns a :class:`LlamaCppPythonClient` unless
    ``config.external_model.enabled`` is set, in which case the agent
    runs on the configured external provider (LM Studio / OpenAI /
    Anthropic). If the external client can't be built or reached, this
    prints a warning and falls back to the local model — the robot is
    never left without a brain because a cloud endpoint is down."""
    ext = getattr(config, "external_model", None)
    if ext is not None and getattr(ext, "enabled", False):
        from jaeger_os.core.models.external_model import ExternalModelClient, ExternalModelError
        try:
            client = ExternalModelClient(ext, layout)
            check = client.connectivity_check()
            if not check["ok"]:
                print(f"[jaeger] external model unreachable ({check['detail']}); "
                      "falling back to the local model.", flush=True)
            else:
                print(f"[jaeger] external model: {client.describe()} "
                      f"(reachable, {check['latency_s']}s)", flush=True)
                return client
        except ExternalModelError as exc:
            print(f"[jaeger] external model not configured ({exc}); "
                  "falling back to the local model.", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[jaeger] external model error ({type(exc).__name__}: {exc}); "
                  "falling back to the local model.", flush=True)
    # Local backend selection. ``config.model.backend`` selects which
    # in-process engine loads the weights — llama-cpp-python for GGUF
    # (the default), mlx for Apple-Silicon-optimised MLX models.
    backend = (getattr(config.model, "backend", "") or "llama_cpp_python").lower()
    if backend in ("mlx", "mlx-lm", "mlx_lm"):
        from jaeger_os.core.models.mlx_client import MlxClient
        return MlxClient(config.model.model_path, warmup=warmup)
    return LlamaCppPythonClient(config.model, warmup=warmup)


# ---------------------------------------------------------------------------
# Self-test (no LLM)
# ---------------------------------------------------------------------------
def self_test(layout: InstanceLayout) -> int:
    """Exercise the sandbox + memory + skill loader without touching the LLM."""
    jaeger_tools.bind(layout)
    print(f"[jaeger] self-test against {layout.root}")
    checks: list[tuple[str, Any]] = [
        ("get_time", lambda: jaeger_tools.get_time()),
        ("calculate", lambda: jaeger_tools.calculate("(2+3)*4")),
        ("system_status", lambda: jaeger_tools.system_status()),
        ("write_file (allowed)", lambda: jaeger_tools.file_write("self_test/hello.txt", "hello jaeger")),
        ("read_file (allowed)",  lambda: jaeger_tools.file_read("skills/self_test/hello.txt")),
        ("write_file (.. escape rejected)", lambda: jaeger_tools.file_write("../identity.yaml", "bad")),
        ("write_file (absolute path rejected)", lambda: jaeger_tools.file_write("/etc/passwd", "bad")),
        ("read_file (credentials rejected)", lambda: jaeger_tools.file_read("credentials/anything")),
        ("remember/recall", lambda: (jaeger_tools.remember("k", "v"), jaeger_tools.recall("k"))),
        ("list_facts", lambda: jaeger_tools.list_facts()),
        ("forget", lambda: jaeger_tools.forget("k")),
        ("list_skill_dir", lambda: jaeger_tools.list_skill_dir(".")),
    ]
    fail = 0
    for label, fn in checks:
        try:
            result = fn()
        except Exception as exc:
            print(f"== {label} == FAILED: {exc}")
            fail += 1
            continue
        as_str = json.dumps(result, ensure_ascii=True, default=str)
        if len(as_str) > 140:
            as_str = as_str[:137] + "..."
        print(f"== {label} == {as_str}")
    # Sandbox negative-checks should have returned a dict with written=False / read=False
    # — confirm we got the rejection shape, not a stack trace.
    try:
        bad = jaeger_tools.file_write("../identity.yaml", "X")
        assert bad.get("written") is False, "sandbox failed to reject .. escape"
        bad2 = jaeger_tools.file_write("/etc/passwd", "X")
        assert bad2.get("written") is False, "sandbox failed to reject absolute path"
        bad3 = jaeger_tools.file_read("credentials/anything")
        assert bad3.get("read") is False, "sandbox failed to reject credentials read"
        print("== sandbox enforcement == OK (.. + abs path + credentials all rejected)")
    except AssertionError as exc:
        print(f"== sandbox enforcement == FAILED: {exc}")
        fail += 1

    # Skill discovery
    try:
        from jaeger_os.core.skills.skill_loader import discover_skills
        discovered = discover_skills(layout)
        names = [f"{s.name}_v{s.version}({s.zone})" for s in discovered]
        print(f"== skill discovery == {names or '(none yet — core skills/ empty)'}")
    except Exception as exc:
        print(f"== skill discovery == FAILED: {exc}")
        fail += 1

    # Credentials: round-trip + perm enforcement
    try:
        creds.set_credential(layout, "self_test_token", "abc123")
        v = creds.get_credential(layout, "self_test_token")
        assert v == "abc123", f"value round-trip mismatch: {v!r}"
        path = layout.credentials_dir / "self_test_token"
        # Verify perms
        import stat as _stat
        mode = _stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

        # Loosen perms and confirm refusal
        os.chmod(path, 0o644)
        try:
            creds.get_credential(layout, "self_test_token")
            raise AssertionError("get_credential should have refused on 0o644")
        except creds.CredentialError:
            pass
        os.chmod(path, 0o600)

        # Invalid name rejection
        try:
            creds.set_credential(layout, "../etc/passwd", "X")
            raise AssertionError("invalid name should have been rejected")
        except creds.CredentialError:
            pass

        creds.delete_credential(layout, "self_test_token")
        print("== credentials == OK (round-trip, perm enforcement, name validation)")
    except Exception as exc:
        print(f"== credentials == FAILED: {exc}")
        fail += 1

    # Migrations discovery
    try:
        from jaeger_os.core.instance.migrations import discover_migrations
        migs = discover_migrations()
        print(f"== migrations == {[m['name'] for m in migs] or '(none registered — at head)'}")
    except Exception as exc:
        print(f"== migrations == FAILED: {exc}")
        fail += 1

    return 0 if fail == 0 else 1


# ---------------------------------------------------------------------------
# Credential CLI handlers
# ---------------------------------------------------------------------------
def _cli_set_credential(layout: InstanceLayout, name: str) -> int:
    """Read the value from stdin so it never appears in shell history.

    If stdin is a TTY, prompt with getpass (the value is echoed-suppressed).
    Otherwise read a single line from stdin (allows `echo $TOK | jaeger
    --set-credential NAME` for scripted setups; the user accepts that
    risk by piping).
    """
    import getpass
    if sys.stdin.isatty():
        try:
            value = getpass.getpass(f"Value for credential {name!r} (input hidden): ")
        except KeyboardInterrupt:
            print()
            return 2
    else:
        value = sys.stdin.readline().rstrip("\n")
    if not value:
        print("[jaeger] empty value — refusing to store.", file=sys.stderr, flush=True)
        return 2
    try:
        path = creds.set_credential(layout, name, value)
    except creds.CredentialError as exc:
        print(f"[jaeger] {exc}", file=sys.stderr, flush=True)
        return 2
    print(f"[jaeger] stored credential {name!r} at {path} (mode 0600).")
    return 0


def _cli_list_credentials(layout: InstanceLayout) -> int:
    names = creds.list_credentials(layout)
    if not names:
        print("(no credentials stored yet)")
        return 0
    print("Credentials in", layout.credentials_dir)
    for n in names:
        print(f"  {n}")
    return 0


def _cli_delete_credential(layout: InstanceLayout, name: str) -> int:
    try:
        existed = creds.delete_credential(layout, name)
    except creds.CredentialError as exc:
        print(f"[jaeger] {exc}", file=sys.stderr, flush=True)
        return 2
    if existed:
        print(f"[jaeger] deleted credential {name!r}.")
        return 0
    print(f"[jaeger] no credential named {name!r} to delete.")
    return 1


def _cli_migrate(layout: InstanceLayout) -> int:
    from jaeger_os.core.instance.migrations import run_pending_migrations

    try:
        applied = run_pending_migrations(layout)
    except Exception as exc:
        print(f"[jaeger] migration failed: {exc}", file=sys.stderr, flush=True)
        return 2
    if not applied:
        print("[jaeger] instance is already at the installed core version — nothing to migrate.")
    else:
        print(f"[jaeger] applied {len(applied)} migration(s):")
        for name in applied:
            print(f"  ✓ {name}")
    return 0


# ---------------------------------------------------------------------------
# Instance management — admin commands. All exit after running and never
# enter the chat loop. Mutating ops (delete / clear) prompt for confirmation
# unless --force is passed (or stdin is not a TTY, where confirmation is
# auto-yes so scripts can run them in CI).
# ---------------------------------------------------------------------------
def _instance_root() -> "Path":
    """Parent directory containing all instances. Same resolution rules as
    a single instance, just without the trailing instance-name component."""
    # resolve_instance_dir("__probe__") is built deterministically from the
    # same parent. Strip the leaf to get the root.
    return resolve_instance_dir("__probe__").parent


def _list_instances() -> list[tuple[str, "Path", bool]]:
    """Return [(name, path, has_manifest), ...] for every directory under
    the instance root. has_manifest is True when the dir looks like a
    valid Jaeger instance (manifest.json present)."""
    root = _instance_root()
    if not root.exists():
        return []
    instances = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        has_manifest = (child / "manifest.json").exists()
        instances.append((child.name, child, has_manifest))
    return instances


def _cli_list_instances() -> int:
    """Print all instances under the root with their identity + status."""
    instances = _list_instances()
    root = _instance_root()
    print(f"Instances under {root}:")
    if not instances:
        print("  (none yet — run `./run.sh setup` to create one)")
        return 0
    current = default_instance_name()
    for name, path, has_manifest in instances:
        marker = " *" if name == current else "  "
        if has_manifest:
            # Try to read the instance's identity for a one-line summary.
            try:
                from jaeger_os.core.instance.schemas import Identity, load_yaml
                identity = load_yaml(path / "identity.yaml", Identity)
                summary = f"{identity.name!r} — {identity.role}"
            except Exception:
                summary = "(unreadable identity.yaml)"
        else:
            summary = "(stub: no manifest.json — partial setup?)"
        print(f"{marker} {name:<24} {summary}")
    print(f"\n* = current (JAEGER_INSTANCE_NAME={current!r})")
    return 0


def _cli_create_instance(name: str, *, force: bool = False) -> int:
    """Non-interactively create a new instance with default identity + config.
    Refuses if the target dir already exists (use --force to overwrite)."""
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if layout.root.exists() and any(layout.root.iterdir()):
        if not force:
            print(f"[jaeger] instance {name!r} already exists at {layout.root} "
                  f"— use --force to overwrite, or pick a different name.",
                  file=sys.stderr, flush=True)
            return 2
        # Overwrite path
        import shutil
        shutil.rmtree(layout.root, ignore_errors=True)

    from jaeger_os.core.instance.schemas import (
        Config, DisplayConfig, Identity, Manifest, ModelConfig, SkillsConfig,
        dump_json, dump_yaml,
    )
    from jaeger_os.core.models.model_resolver import DEFAULT_MODEL

    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(
        name=name.capitalize(),
        role="local AI assistant",
        personality=(
            "Concise and direct. Match tool calls to user intent — never "
            "free-text when a tool exists for the request."
        ),
    ))
    dump_yaml(layout.config_path, Config(
        instance_name=name,
        # Store the registry NAME, not a resolved absolute path —
        # ``LlamaCppPythonClient`` resolves through ``model_resolver``
        # at boot, which auto-downloads from HF Hub if the file isn't
        # in the user cache. Survives moves / new machines unchanged.
        model=ModelConfig(model_path=DEFAULT_MODEL),
        display=DisplayConfig(show_help_on_start=False),
        skills=SkillsConfig(run_smoke_tests=True),
    ))
    dump_json(layout.manifest_path, Manifest(instance_name=name))
    print(f"[jaeger] created instance {name!r} at {layout.root}")
    print(f"         identity.yaml + config.yaml + manifest.json populated with defaults.")
    print(f"         edit identity.yaml / config.yaml to customize, then launch with:")
    print(f"           python -m jaeger_os --instance {name}")
    return 0


def _cli_delete_instance(name: str, *, force: bool = False) -> int:
    """Remove an entire instance directory. PROMPTS for confirmation unless
    --force. Refuses to delete the currently-active instance (per
    JAEGER_INSTANCE_NAME) without --force as a sanity check."""
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.root.exists():
        print(f"[jaeger] no instance {name!r} at {layout.root} — nothing to delete.")
        return 1

    if name == default_instance_name() and not force:
        print(f"[jaeger] {name!r} is the active instance (per JAEGER_INSTANCE_NAME). "
              f"Pass --force to delete it anyway.", file=sys.stderr, flush=True)
        return 2

    if not force:
        if sys.stdin.isatty():
            confirm = input(
                f"[jaeger] delete instance {name!r} at {layout.root}? "
                f"This is irreversible. Type the instance name to confirm: "
            )
            if confirm.strip() != name:
                print("[jaeger] aborted (name didn't match).")
                return 1
        # If stdin isn't a TTY (piped/scripted), require --force explicitly.
        else:
            print(f"[jaeger] non-interactive delete refused; pass --force.", file=sys.stderr)
            return 2

    import shutil
    shutil.rmtree(layout.root)
    print(f"[jaeger] deleted instance {name!r}.")
    return 0


def _cli_clear_instance(name: str, *, force: bool = False) -> int:
    """Reset memory + logs but keep identity / config / manifest / credentials /
    skills. Useful for 'start a clean conversation, don't blow away your setup.'
    """
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.root.exists():
        print(f"[jaeger] no instance {name!r} at {layout.root} — nothing to clear.")
        return 1

    if not force:
        if sys.stdin.isatty():
            confirm = input(
                f"[jaeger] clear memory + logs for instance {name!r}? "
                f"(identity / config / credentials / skills are preserved) [y/N]: "
            )
            if confirm.strip().lower() not in ("y", "yes"):
                print("[jaeger] aborted.")
                return 1
        else:
            print(f"[jaeger] non-interactive clear refused; pass --force.", file=sys.stderr)
            return 2

    import shutil
    cleared = []
    # Memory: wipe everything (facts.json, episodic.jsonl, embeddings.npz, …)
    if layout.memory_dir.exists():
        for entry in layout.memory_dir.iterdir():
            try:
                if entry.is_file():
                    entry.unlink()
                else:
                    shutil.rmtree(entry, ignore_errors=True)
            except Exception as exc:
                print(f"[jaeger] couldn't clear {entry}: {exc}", file=sys.stderr)
        cleared.append("memory/")
    # Logs: drop everything (latency, audit, thinking)
    if layout.logs_dir.exists():
        for entry in layout.logs_dir.iterdir():
            try:
                if entry.is_file():
                    entry.unlink()
                else:
                    shutil.rmtree(entry, ignore_errors=True)
            except Exception as exc:
                print(f"[jaeger] couldn't clear {entry}: {exc}", file=sys.stderr)
        cleared.append("logs/")
    print(f"[jaeger] cleared {name!r}: {', '.join(cleared) or '(nothing to clear)'}")
    print(f"         preserved: identity.yaml, config.yaml, manifest.json, credentials/, skills/")
    return 0


# ---------------------------------------------------------------------------
# CLI argparse + main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jaeger: self-improving local agent.")
    p.add_argument("prompt", nargs="*", help="Optional one-shot command.")
    p.add_argument("--instance", type=str, default=None,
                   help="Instance name (default: JAEGER_INSTANCE_NAME or 'default').")
    # ``--setup`` removed in 0.2.0 — use ``jaeger setup`` (INST-2).
    p.add_argument("--self-test", action="store_true",
                   help="Run the sandbox/memory/skill smoke tests without loading the LLM.")
    p.add_argument("--doctor", action="store_true",
                   help="Check that every dependency + system library is ready, then exit.")
    p.add_argument("--doctor-json", action="store_true",
                   help="With --doctor: emit the report as JSON instead of "
                        "the human-readable table. Useful for monitoring.")
    p.add_argument("--doctor-check", action="store_true",
                   help="With --doctor: non-interactive mode. Skip the "
                        "install-missing prompt; exit code reflects health.")
    p.add_argument("--no-warmup", action="store_true", help="Skip llama-cpp warmup.")
    p.add_argument("--no-cron", action="store_true", help="Don't start the cron runner.")
    p.add_argument("--set-credential", metavar="NAME",
                   help="Store a credential under this name (value read from stdin), then exit.")
    p.add_argument("--list-credentials", action="store_true",
                   help="List stored credential names (values never printed) and exit.")
    p.add_argument("--delete-credential", metavar="NAME",
                   help="Delete a stored credential by name and exit.")
    # ``--migrate``, ``--list-instances``, ``--create-instance``,
    # ``--delete-instance``, ``--clear-instance`` removed in 0.2.0
    # — use ``jaeger migrate`` and ``jaeger instance {list,delete,clear}``
    # (INST-2). The wizard creates new instances directly via
    # ``jaeger setup --name NAME``; the explicit ``--create-instance``
    # noninteractive shortcut is no longer the recommended path.
    # ``--force`` stays — still used by deprecated paths inside
    # main.py that haven't been routed to the verb subsystem yet
    # (kept narrow during the cutover).
    p.add_argument("--force", action="store_true",
                   help="Skip confirmation prompts on destructive operations.")
    p.add_argument("--with-memory", action="store_true",
                   help=("Carry conversation history across turns (load last 5 "
                         "episodic turns + accumulate within session). Auto-on "
                         "in interactive mode; off for one-shot/bench runs."))
    p.add_argument("--with-mcp", action="store_true",
                   help=("Connect to MCP servers from plugins/mcp_config.json "
                         "and expose their tools through the agent surface."))
    p.add_argument("--think", action="store_true",
                   help=("Run a background chain-of-thought call after each "
                         "user turn. Logs to plugins/thinking.jsonl. Shares the "
                         "main LLM lock so it never decodes concurrently."))
    p.add_argument("--voice", action="store_true",
                   help=("Launch the voice loop daemon instead of CLI chat. "
                         "All flags after --voice are forwarded to voice_loop "
                         "(--stt-mode, --barge-in, --no-aec, --require-wake-word, "
                         "--no-chimes, --fast-model, --accurate-model). "
                         "See `python -m jaeger_os --voice --help` for the "
                         "voice flag surface."))
    p.add_argument("--daemon", action="store_true",
                   help=("Run headless: boot the pipeline, start the cron "
                         "runner, and work the Deep Think queue in the "
                         "background. No TUI, no interactive input. Runs "
                         "until SIGTERM/SIGINT. See deploy/ for the launchd "
                         "plist."))
    return p.parse_args()


@dataclass
class TUIBootResult:
    """Returned from :func:`boot_for_tui`. ``cleanup`` releases the
    instance lock + shuts down extensions; call it from the TUI's
    finally block."""

    client: Any
    layout: InstanceLayout
    cleanup: Any  # Callable[[], None]


def boot_for_tui(
    *,
    instance_name: str | None = None,
    with_memory: bool = True,
    warmup: bool = True,
) -> TUIBootResult:
    """Boot the jaeger pipeline for an interactive TUI session.

    Mirrors the subset of :func:`main` that ``cli_loop`` needs:
    instance resolve → manifest gate → lock → bind tools → load model
    → build agent → prewarm. Returns the client (for
    :func:`run_command`) and a cleanup callable.

    The TUI doesn't use the cron runner, MCP plugins, or thinking
    extensions — keeping the surface small so the boot is fast and
    the failure modes match ``cli_loop`` 1:1.
    """
    instance_name = instance_name or default_instance_name()
    root = resolve_instance_dir(instance_name)
    layout = InstanceLayout(root=root)

    if not layout.exists():
        layout = run_wizard(force=False, instance_name=instance_name)

    try:
        manifest = check_manifest(layout)
    except CoreVersionMismatch:
        from jaeger_os.core.instance.migrations import run_pending_migrations
        run_pending_migrations(layout)
        manifest = check_manifest(layout)

    lock = InstanceLock(layout)
    lock.acquire()

    try:
        jaeger_tools.bind(layout)
        touch_manifest_started(layout, manifest)

        config: Config = load_yaml(layout.config_path, Config)
        # INST-11: honour the user's optional workspace override
        # (config.yaml: workspace.location). Re-bind with the path so
        # ``file_write("workspace/...")`` lands wherever the user wants.
        if getattr(config.workspace, "location", None):
            jaeger_tools.bind(layout, workspace_override=config.workspace.location)
        _pipeline["layout"] = layout
        _pipeline["config"] = config
        _pipeline["show_latency"] = config.display.show_latency
        _pipeline["show_tool_activity"] = config.display.show_tool_activity
        _pipeline["show_help_on_start"] = False
        _pipeline["system_prompt"] = prompt_module.build_system_prompt(layout)
        _pipeline["with_memory"] = with_memory
        # Phase-7: optional toolset restriction at boot. ``JAEGER_TOOLSETS=...``
        # (comma-separated) keeps only the named Hermes-style groups in the
        # agent's catalogue; unset → every registered tool. Validates eagerly
        # so a typo surfaces at boot, not on the first turn.
        _pipeline["toolsets"] = _parse_toolsets_env()

        # Wire the interactive permission provider so tier-gated tools
        # (run_in_venv, install_package, …) prompt the user instead of
        # being auto-denied. On non-interactive stdin it denies safely.
        _preflight_log()
        install_policy(PermissionPolicy(confirmation=_confirmation_provider(config, layout)))

        client = make_client(config, layout, warmup=warmup)
        # Skills that loop with the model — macos_computer's computer_do —
        # read the live client from _pipeline["client"]. The full CLI path
        # sets this in init_extensions, which the TUI deliberately does
        # not run; without this line every computer_do call in the TUI
        # fails with "no LLM client available for the loop".
        _pipeline["client"] = client
        agent = _get_agent(client)
        # Wire plugin readiness into per-tool ``check_fn``. Tools
        # whose backing plugin isn't ready (missing libs, missing
        # env / creds, wrong platform) become unavailable — the
        # model's ``tools`` schema view filters them out so it
        # can't reach for ``send_message`` when Discord isn't set
        # up. The wiring is idempotent + best-effort.
        try:
            from jaeger_os.core.tools.availability import wire_availability_checks
            wired = wire_availability_checks(agent)
            if wired:
                print(f"[jaeger] availability wired for {wired} plugin-backed tool(s)",
                      flush=True)
        except Exception:  # noqa: BLE001 — never break boot over this
            pass
        if warmup:
            prewarm(client)
            warm_plugins(config)

        llm_lock = threading.Lock()
        _pipeline["llm_lock"] = llm_lock
    except Exception:
        lock.release()
        raise

    def cleanup() -> None:
        try:
            shutdown_extensions(wait=False)
        except Exception:
            pass
        try:
            lock.release()
        except Exception:
            pass

    return TUIBootResult(client=client, layout=layout, cleanup=cleanup)


def boot_for_daemon(
    *,
    instance_name: str | None = None,
    with_memory: bool = True,
    warmup: bool = True,
) -> TUIBootResult:
    """Boot the jaeger pipeline for the daemon's child process.

    The daemon's boot is **the same** as the TUI's — instance resolve →
    manifest gate → lock → bind tools → load model → build agent →
    prewarm. The only difference is the caller: the daemon owns the
    instance lock for its whole lifetime; clients (TUI / attach / GUI)
    just open the socket. This function exists as a named entry point
    so the lifecycle factory in ``daemon/cli.py`` doesn't have to
    import ``boot_for_tui`` (and so we can swap the daemon's boot
    without touching the TUI's path if they diverge later).

    Returns the same :class:`TUIBootResult`; the daemon doesn't need
    a separate result type — it just keeps ``client`` + ``layout``
    alive and calls ``cleanup()`` on shutdown.
    """
    return boot_for_tui(
        instance_name=instance_name,
        with_memory=with_memory,
        warmup=warmup,
    )


def switch_model(new_model: str, *, warmup: bool = True) -> Any:
    """Swap the resident LLM to a different model — SAME instance.

    Phase-0 of Deep Think (see docs/deep_think_design.md). The mode
    manager calls this to swap Realtime ⇄ Deep-Think models: unload the
    current model, load ``new_model``, rebuild the agent. The instance,
    layout, lock, tools, and memory all stay bound — only the model and
    its agent change.

    ``new_model`` is a model_resolver registry name (e.g.
    ``qwen3-coder-30b-a3b-q4_k_m``) or a path; it resolves through
    :func:`model_resolver.resolve_model_path`.

    IMPORTANT — RAM: the caller MUST drop its reference to the OLD
    client before calling this. On a unified-memory Mac, holding both
    references means both model weights are briefly co-resident, which
    can OOM a 32 GB machine. This function nulls ``_pipeline["client"]``
    and forces a GC before allocating the new model, but it cannot
    reach the caller's own variable — drop it on your side first.

    Returns the new client.
    """
    import gc

    config = _pipeline.get("config")
    if config is None:
        raise RuntimeError("switch_model: no active pipeline — boot first.")

    # Model swap is a llama-cpp feature — it unloads/loads GGUF weights.
    # When the brain is an external model there is nothing local to swap;
    # Deep Think keeps running on that same external model.
    ext = getattr(config, "external_model", None)
    if ext is not None and getattr(ext, "enabled", False):
        existing = _pipeline.get("client")
        if existing is not None:
            return existing
        return make_client(config, _pipeline.get("layout"), warmup=warmup)

    # New ModelConfig: identical tuning (ctx, gpu_layers, …), new model.
    new_model_cfg = config.model.model_copy(update={"model_path": new_model})

    # Drop the old model so llama-cpp frees its weights BEFORE we
    # allocate the new one. _agent_cache holds the old agent (which
    # references the old client/model) — clear it too.
    _pipeline["client"] = None
    _agent_cache.clear()
    gc.collect()

    client = LlamaCppPythonClient(new_model_cfg, warmup=warmup)
    _get_agent(client)            # rebuilds the agent + reloads skills
    if warmup:
        prewarm(client)

    # Persist so subsequent reads see the active model.
    config.model = new_model_cfg
    _pipeline["client"] = client
    return client


def run_daemon(*, instance_name: str | None = None,
               poll_seconds: int = 60) -> int:
    """Headless daemon: boot the pipeline, start the cron runner, and
    work the Deep Think queue in the background.

    No TUI, no interactive input. Runs until SIGTERM/SIGINT. Intended
    to run under launchd (see deploy/) so the robot operates
    unattended. Output goes to stdout — launchd redirects it to a log.
    """
    import signal as _signal

    from jaeger_os.core.background.deep_think import queue_for_layout
    from jaeger_os.core.models.model_resolver import DEFAULT_CODER_MODEL, DEFAULT_MODEL
    from jaeger_os.core.prompts.reflection import reflect_on_task, save_reflection

    print("[jaeger-daemon] booting…", flush=True)
    boot = boot_for_tui(instance_name=instance_name, with_memory=True,
                        warmup=True)
    layout = boot.layout
    queue = queue_for_layout(layout)

    _stop = {"flag": False}

    def _on_signal(signum: int, _frame: Any) -> None:
        print(f"[jaeger-daemon] signal {signum} — shutting down…", flush=True)
        _stop["flag"] = True

    _signal.signal(_signal.SIGTERM, _on_signal)
    _signal.signal(_signal.SIGINT, _on_signal)

    # Cron runner — scheduled prompts fire on the shared llm_lock.
    cron = None
    try:
        llm_lock = _pipeline.get("llm_lock")

        def _cron_cb(prompt: str, session_key: str | None = None) -> None:
            run_command(boot.client, prompt, session_key=session_key)

        cron = CronRunner(_cron_cb, llm_lock=llm_lock)
        cron.start()
        print("[jaeger-daemon] cron runner started.", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger-daemon] cron runner skipped: {exc}", flush=True)

    print(f"[jaeger-daemon] ready — polling every {poll_seconds}s. "
          "Ctrl-C / SIGTERM to stop.", flush=True)
    client = boot.client
    try:
        while not _stop["flag"]:
            task = queue.next_pending()
            if task is not None:
                # There's approved work — swap to the coder model, drain
                # the queue, swap back. Same shape as the TUI's Deep
                # Think loop, headless.
                print(f"[jaeger-daemon] Deep Think: {queue.summary()}",
                      flush=True)
                try:
                    client = switch_model(DEFAULT_CODER_MODEL)
                except Exception as exc:  # noqa: BLE001
                    print(f"[jaeger-daemon] coder model load failed: {exc}",
                          flush=True)
                    client = switch_model(DEFAULT_MODEL)
                    time.sleep(poll_seconds)
                    continue
                while not _stop["flag"]:
                    task = queue.next_pending()
                    if task is None:
                        break
                    queue.mark_in_progress(task.id)
                    print(f"[jaeger-daemon] working {task.id}: "
                          f"{task.description}", flush=True)
                    outcome = "done"
                    try:
                        run_command(
                            client,
                            f"Deep Think task — complete it fully, writing "
                            f"files into skills/ and installing deps as "
                            f"needed:\n\n{task.description}",
                            session_key=f"daemon_{task.id}",
                        )
                        queue.mark_done(task.id, "completed by daemon")
                    except Exception as exc:  # noqa: BLE001
                        outcome = f"failed: {exc}"
                        queue.mark_failed(task.id, str(exc))
                    try:
                        refl = reflect_on_task(client, task.description, outcome)
                        if refl:
                            save_reflection(layout, task.description,
                                            outcome, refl)
                    except Exception:  # noqa: BLE001
                        pass
                # Swap the realtime model back in for cron / messaging.
                try:
                    client = switch_model(DEFAULT_MODEL)
                except Exception as exc:  # noqa: BLE001
                    print(f"[jaeger-daemon] realtime reload failed: {exc}",
                          flush=True)
            # Idle wait — short sleeps so a stop signal is responsive.
            slept = 0
            while slept < poll_seconds and not _stop["flag"]:
                time.sleep(min(2, poll_seconds - slept))
                slept += 2
    finally:
        if cron is not None:
            try:
                cron.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        try:
            boot.cleanup()
        except Exception:  # noqa: BLE001
            pass
    print("[jaeger-daemon] stopped.", flush=True)
    return 0


def main() -> int:
    # Daemon subcommands — ``jaeger start | stop | status | restart`` —
    # peel off BEFORE argparse so they don't collide with the positional
    # ``prompt`` argument the legacy CLI takes. Standalone ``jaeger``
    # (no subcommand) falls through to the existing TUI path unchanged.
    # 0.2.6 cleanup: the pre-0.2.0 legacy-layout migration (flat
    # ``~/.jaeger/<name>/`` → nested ``~/.jaeger/instances/<name>/``)
    # is gone. JROS instances were prototypes at that point; nothing
    # operational was running off the 0.1.0 shape. The new operator-
    # state location at ``<install_root>/.jaeger_os/`` is a fresh
    # start — operators who want to keep an old instance can copy
    # it across manually.

    from jaeger_os.daemon.cli import dispatch as _daemon_dispatch, is_daemon_subcommand as _is_daemon
    if _is_daemon(sys.argv[1:]):
        return _daemon_dispatch(sys.argv[1:])
    # If --voice is present, peel it off and delegate to the voice_loop
    # daemon. Voice_loop has its own argparse for STT mode, barge-in, AEC,
    # wake-word, chimes, model names, etc. — every flag the user types
    # after --voice flows through unchanged.
    if "--voice" in sys.argv[1:]:
        sys.argv.remove("--voice")
        from .plugins.voice_loop import main as voice_main
        return voice_main()
    # --tui launches the rich TUI. Peel it off and delegate to the TUI
    # entry point (which handles --instance / --banner-only) — same
    # pattern as --voice. This is what `jaeger-os --tui` resolves to.
    if "--tui" in sys.argv[1:]:
        sys.argv.remove("--tui")
        from .interfaces.tui.__main__ import main as tui_main
        return tui_main()
    args = parse_args()
    # --doctor: verify every dependency + system library, offer to
    # install whatever is missing, then exit. When the named (or
    # default) instance is already set up, also validate its
    # config.yaml + model.path + ctx — the failures we see most often.
    if getattr(args, "doctor", False):
        from jaeger_os.core.runtime.preflight import (
            check_environment, check_instance, fixable, format_report,
            install_missing, missing, report_as_json,
        )
        # Try to bind an instance for the deeper config check. Fall
        # back to environment-only when no instance exists yet (a fresh
        # ``pip install jaeger-os`` user running --doctor pre-setup).
        try:
            _doc_inst = args.instance or default_instance_name()
            _doc_root = resolve_instance_dir(_doc_inst)
            _doc_layout = InstanceLayout(root=_doc_root)
            if (_doc_root / "config.yaml").is_file():
                checks = check_instance(_doc_layout)
            else:
                checks = check_environment()
        except Exception:  # noqa: BLE001
            checks = check_environment()
        # --doctor-json: machine-readable output for scripting /
        # monitoring agents. Skip the human-readable table and the
        # install prompt; exit code is health-only.
        if getattr(args, "doctor_json", False):
            print(report_as_json(checks))
            return 1 if missing(checks) else 0
        print(format_report(checks))
        cmds = fixable(checks)
        # --doctor-check: non-interactive. Skip the install prompt
        # even when stdin is a TTY; exit code reflects health.
        if cmds and sys.stdin.isatty() and not getattr(args, "doctor_check", False):
            print("  These can be installed for you:")
            for cmd in cmds:
                print(f"    {' '.join(cmd)}")
            try:
                ans = input("  Install them now? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans.startswith("y"):
                print()
                checks = install_missing(checks)
                print(format_report(checks))
                if missing(checks):
                    print("  Anything still missing may just need a restart to "
                          "register — re-run `jaeger-os --doctor` to confirm.")
        return 1 if missing(checks) else 0
    # Headless daemon mode — boot, cron, work the Deep Think queue.
    if getattr(args, "daemon", False):
        return run_daemon(instance_name=args.instance)
    instance_name = args.instance or default_instance_name()
    root = resolve_instance_dir(instance_name)
    layout = InstanceLayout(root=root)

    # Instance-management commands now live under ``jaeger setup`` /
    # ``jaeger instance {list,use,inspect,delete,clear}`` / ``jaeger
    # migrate`` — see ``daemon/instance_verbs.py`` (INST-2). The old
    # ``--list-instances`` / ``--create-instance`` / ``--delete-
    # instance`` / ``--clear-instance`` / ``--migrate`` flags were
    # removed in 0.2.0; legacy callers get an argparse error and
    # should switch to the new verb form.

    # Self-test runs without identity/config/manifest — it only exercises
    # the framework code paths (sandbox, memory, skill loader, credentials,
    # migration discovery). Skip the wizard and just create the subdirs.
    if args.self_test:
        layout.root.mkdir(parents=True, exist_ok=True)
        layout.ensure_dirs()
        return self_test(layout)

    # First-run / missing-instance: auto-fire the wizard. Explicit
    # ``jaeger setup`` runs through the daemon-cli dispatcher and
    # never reaches this branch.
    if not layout.exists():
        layout = run_wizard(force=False, instance_name=instance_name)

    # Manifest gate. On version mismatch try the migration runner; only
    # refuse-to-start if migrations don't bring us to parity.
    try:
        manifest = check_manifest(layout)
    except CoreVersionMismatch:
        try:
            from jaeger_os.core.instance.migrations import run_pending_migrations
            applied = run_pending_migrations(layout)
            if applied:
                print(f"[jaeger] applied {len(applied)} migration(s) to reach core {CORE_VERSION}: "
                      + ", ".join(applied), flush=True)
            manifest = check_manifest(layout)  # must pass now
        except Exception as exc:
            print(f"[jaeger] refuse-to-start: {exc}", file=sys.stderr, flush=True)
            return 2

    # Interactive use (no one-shot prompt) → the TUI is the interface.
    # Every exit-flag mode is already handled above and no instance lock
    # is held yet, so this hand-off is clean: the TUI does its own boot.
    #
    # 0.2.6: thread --instance NAME through to the TUI. Pre-0.2.6 this
    # called tui_main() with no args; the TUI then ignored argv,
    # silently fell back to the deleted ``jaeger_os/instance/default/``
    # bundled path, and auto-fired the wizard against ``default`` even
    # when the operator had passed ``--instance jros-dev`` (or any
    # other name). Pass the flag through as a CLI arg the TUI's own
    # argparse honours.
    if not " ".join(args.prompt).strip():
        from .interfaces.tui.__main__ import main as tui_main
        tui_argv: list[str] = []
        if args.instance:
            tui_argv = ["--instance", args.instance]
        return tui_main(tui_argv)

    # Lock
    lock = InstanceLock(layout)
    try:
        lock.acquire()
    except RuntimeError as exc:
        print(f"[jaeger] {exc}", file=sys.stderr, flush=True)
        return 2

    try:
        # Bind tools/memory + record start time on the manifest
        jaeger_tools.bind(layout)
        touch_manifest_started(layout, manifest)

        # INST-11: re-bind with workspace override if the user set
        # ``workspace.location`` in config.yaml. Read config eagerly
        # so the agent's writes route correctly from the first turn.
        try:
            _cfg_for_workspace = load_yaml(layout.config_path, Config)
            if getattr(_cfg_for_workspace.workspace, "location", None):
                jaeger_tools.bind(
                    layout,
                    workspace_override=_cfg_for_workspace.workspace.location,
                )
        except Exception:  # noqa: BLE001 — config load happens again below
            pass

        # Credential management — these subcommands skip model load.
        if args.set_credential:
            return _cli_set_credential(layout, args.set_credential)
        if args.list_credentials:
            return _cli_list_credentials(layout)
        if args.delete_credential:
            return _cli_delete_credential(layout, args.delete_credential)
        # ``--migrate`` removed in 0.2.0 — use ``jaeger migrate``.

        # NB: --self-test runs earlier in main() (before wizard / manifest / lock)
        # so it works against a brand-new install with no identity yet.

        config: Config = load_yaml(layout.config_path, Config)
        _pipeline["layout"] = layout
        _pipeline["config"] = config
        _pipeline["show_latency"] = config.display.show_latency
        _pipeline["show_tool_activity"] = config.display.show_tool_activity
        _pipeline["show_help_on_start"] = config.display.show_help_on_start
        _pipeline["system_prompt"] = prompt_module.build_system_prompt(layout)

        # Log rotation at startup — idempotent, never blocks the boot.
        try:
            rep = log_rotation.rotate_now(layout, config.retention)
            if rep["rotated"] or rep["pruned_by_age"] or rep["pruned_by_size"]:
                print(f"[jaeger] log rotation: rotated={rep['rotated']} "
                      f"pruned_age={rep['pruned_by_age']} "
                      f"pruned_size={rep['pruned_by_size']}", flush=True)
        except Exception as exc:
            print(f"[jaeger] log rotation skipped: {exc}", flush=True)

        # Interactive permission provider — tier-gated tools prompt the
        # user rather than auto-denying. Safe on non-interactive stdin.
        _preflight_log()
        install_policy(PermissionPolicy(confirmation=_confirmation_provider(config, layout)))

        client = make_client(config, layout, warmup=not args.no_warmup)
        # Force agent build now so skills load before the first prompt.
        _get_agent(client)
        # Prewarm KV cache (system prompt + tool schema) so the first
        # user-facing turn isn't cold. Same trick python_pydantic_ai uses.
        if not args.no_warmup:
            prewarm(client)
            warm_plugins(config)

        # Cron runner: same llm_lock the chat loop uses, so a scheduled
        # prompt firing mid-conversation serializes cleanly.
        llm_lock = threading.Lock()
        _pipeline["llm_lock"] = llm_lock
        cron_runner: CronRunner | None = None
        if not args.no_cron:
            def _cron_callback(prompt: str, session_key: str | None = None) -> None:
                run_command(client, prompt, session_key=session_key)

            def _daily_housekeeping() -> None:
                try:
                    rep = log_rotation.rotate_now(layout, config.retention)
                    if rep["rotated"] or rep["pruned_by_age"] or rep["pruned_by_size"]:
                        print(f"[jaeger-cron] housekeeping: {rep}", flush=True)
                except Exception as exc:
                    print(f"[jaeger-cron] housekeeping skipped: {exc}", flush=True)

            cron_runner = CronRunner(
                _cron_callback, llm_lock=llm_lock,
                housekeeping=_daily_housekeeping,
            )
            cron_runner.start()

        prompt = " ".join(args.prompt).strip()
        # Interactive chat assumes the user wants the conversation to remember
        # itself across turns. One-shot / bench runs default to off so the
        # MANDATORY rules at the top of the system prompt aren't diluted by
        # accumulated history. Explicit --with-memory always wins.
        with_memory = bool(args.with_memory) or os.environ.get("JAEGER_WITH_MEMORY") == "1"
        if not prompt and not with_memory:
            with_memory = True
        # Patch args so init_extensions picks up the resolved value
        args.with_memory = with_memory

        # Wire MCP / thinking / memory through one place. Also seeds
        # _pipeline["llm_lock"] when --think is on, but only if it's not
        # already set by the cron runner above.
        prev_lock = _pipeline.get("llm_lock")
        init_extensions(args, client)
        if prev_lock is not None:
            _pipeline["llm_lock"] = prev_lock

        try:
            # `prompt` is guaranteed non-empty here — the no-prompt
            # interactive case was routed to the TUI before the lock.
            run_command(client, prompt)
            return 0
        finally:
            if cron_runner is not None:
                cron_runner.shutdown(wait=False)
            shutdown_extensions(wait=False)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
