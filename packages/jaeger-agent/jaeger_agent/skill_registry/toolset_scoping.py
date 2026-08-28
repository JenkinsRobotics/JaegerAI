"""Toolset scoping — the agent sees a small CORE set every turn; the
rest are grouped into named toolsets it loads on demand.

Two kinds of toolset:

  • **built-in classes** — the ~55 primitive tools grouped here by hand
    (``files``, ``code``, ``media``, …). They are not skills, just the
    raw surface, classified.
  • **skill toolsets** — registered at runtime by the skill loader. A
    skill IS a toolset: an experienced bundle of tools (+ the process
    to use them, which lives in the skill itself). The loader captures
    exactly which tools a skill registers and names that set after the
    skill — so a new skill becomes a loadable toolset with no edit here.

Why scope at all: routing accuracy on a local model degrades as the
visible tool count grows. The CORE set (~17 common tools) covers most
turns; ``load_tools`` widens the view when a task needs more. The
active set only ever GROWS within a session, so the tool-schema KV
prefix is re-prefilled at most once per widening, never thrashed.

All tools stay REGISTERED on the agent regardless — this only controls
what appears in the schema the model sees. A tool in no toolset is
visible by default (fail-open): a new tool is never silently hidden.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token


def _scoping_enabled() -> bool:
    """Lean tool surface. Opt-in.

    Default OFF: every registered tool is visible, including MCP tools
    loaded at boot. A/B on Gemma 4 showed scoping dropped routing
    100% → 67.6%. ``JAEGER_TOOLSET_SCOPING=1`` enables CORE + load_tools.
    ``JAEGER_FULL_TOOLS=1`` forces the full surface even when scoping is on.
    """
    if os.environ.get("JAEGER_FULL_TOOLS", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return False
    val = os.environ.get("JAEGER_TOOLSET_SCOPING", "").strip().lower()
    return val in ("1", "true", "yes", "on")


# Deterministic first-pass routing, equivalent to Hermes focus/toolset
# profiles.  The model still has list_tools/describe_tool/load_tools in CORE
# for ambiguous requests; these hints avoid spending an extra meta-tool turn
# for clear intent.  Matching is intentionally conservative and additive.
_INTENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "files": (r"\b(files?|folders?|director(?:y|ies)|patch|rename|copy|move)\b",),
    "code": (r"\b(code|python|swift|javascript|typescript|shell|terminal|command|test suite|debug|package)\b",),
    "media": (r"\b(image|video|audio|speech|voice|camera|microphone|listen)\b",),
    "web": (r"\b(weather|forecast)\b",),
    "sessions": (r"\b(conversation|session|chat history)\b",),
    "board": (r"\b(board|kanban|card)\b",),
    "scheduling": (r"\b(schedule|cron|remind|recurring)\b",),
    "background": (r"\b(background|long[- ]running|process|job)\b",),
    "identity": (r"\b(your name|identity|soul|persona)\b",),
    "skills": (r"\b(skill|deep think|reflection)\b",),
    "computer_use": (r"\b(click|screen|browser|website|open app|computer)\b",),
    "credentials": (r"\b(credential|api key|secret|password)\b",),
    "plugins": (r"\b(plugin|discord|telegram|slack|message)\b",),
    "email": (r"\b(e-?mail|inbox|mailbox)\b",),
    "smart_home": (r"\b(home assistant|smart home|light|thermostat)\b",),
    "people": (r"\b(person|people|profile|contact notes)\b",),
    "models": (r"\b(model|ollama|lm studio|context window|autonomy mode)\b",),
    "bench": (r"\b(benchmark|eval|evaluation)\b",),
    "diagnostics": (r"\b(diagnostic|self[- ]check|system health|cpu|disk|uptime)\b",),
    "shortcuts": (r"\b(shortcut|shortcuts\.app)\b",),
    "spotlight": (r"\b(spotlight|find .* on (?:my |the )?mac)\b",),
    "calendar": (r"\b(calendar|event|appointment|meeting)\b",),
    "contacts": (r"\b(contacts?\.app|phone number|contact details)\b",),
    "clipboard": (r"\b(clipboard|pasteboard|copy this)\b",),
    "notifications": (r"\b(notification|notify me|banner)\b",),
    "system_control": (r"\b(volume|brightness|dark mode|do not disturb|prevent sleep)\b",),
    "media_control": (r"\b(now playing|playback|pause music|spotify|music\.app)\b",),
    "ocr": (r"\b(ocr|extract text from|read this (?:image|pdf))\b",),
}


def infer_toolsets(text: str) -> set[str]:
    """Return task-relevant toolsets without an LLM routing call."""
    clean = (text or "").lower()
    return {
        toolset
        for toolset, patterns in _INTENT_PATTERNS.items()
        if any(re.search(pattern, clean) for pattern in patterns)
    }


# CORE — always visible when scoping is on. Umbrellas where they route
# well (``memory`` instead of the five fine-grained verbs, ``list_skills``
# instead of skill-dir primitives), but INDIVIDUAL board verbs
# (``board_add``/``board_view``) rather than an ``action=`` umbrella — a
# local model routes over distinct named tools better than one tool's
# action parameter (measured: the kanban umbrella hurt board filing).
CORE: frozenset[str] = frozenset({
    # Time and math — the cheapest, most-routed pair.
    "get_time", "calculate",
    # Files — read + write; ``patch``/``search_files``/``append_file``/
    # ``delete_file`` are in the ``files`` toolset and load on intent.
    "read_file", "write_file",
    # Code execution — high-value; was loadable before, now CORE.
    "execute_code",
    # Web — the two everyday primitives. ``get_weather`` is loadable
    # via the ``web`` toolset for users that don't want it bloating
    # routing on quiet days.
    "web_search", "web_extract",
    # Memory — umbrella + ``recall`` (the everyday read). The other
    # granular verbs (forget / list_facts / search_memory) load via the
    # ``memory_granular`` toolset. ``recall`` is CORE because scoped runs
    # showed the umbrella alone lost the plain "what did I say" cases.
    "memory", "recall",
    # Tasks + board. Individual board verbs (a local model routes over
    # distinct named tools better than one ``action=`` umbrella); the
    # common two are CORE, the rest load via the ``board`` toolset.
    "todo", "board_add", "board_view",
    # Skill discovery (umbrella) + the enum-callable use_skill + delegation.
    # Heavy procedures live behind ``skill(view)`` / ``use_skill(name=…)``.
    "list_skills", "use_skill", "delegate_task",
    # User interaction.
    "clarify", "help_me",
    # Meta — the search + activate primitives, always visible so the model
    # can FIND any tool (list_tools) and bring it in (load_tools) without
    # ever force-fitting a visible tool for one it hasn't looked up.
    "list_tools", "load_tools", "describe_tool",
    # Mail.app reads — CORE so "organize my inbox" hits list_mail instead
    # of execute_code + guessed AppleScript (the 60-tool hang).
    "list_mailboxes", "list_mail", "read_mail", "plan_mail_triage",
    # ``self_check`` (the agent's doctor) lives in the ``diagnostics``
    # toolset, not CORE — loaded on demand like ``run_benchmark``. The
    # old ``system_health`` was kept out entirely because "do a self
    # check" stalled in prefill (the model dithered between
    # ``system_health`` and ``system_status``). The 2026-06-20 rename to
    # ``self_check`` + this generation's engine/gemma fixes removed that:
    # "do a self check" now routes in ~0.2s TTFT.
})


# ── Lean surface (hermes-style) ──────────────────────────────────────
# A local model routes far better over ~20 curated tools than ~60. This
# is the surface the model sees every turn; everything else stays
# REGISTERED (callable / importable) but off the model's view. The set
# mirrors hermes's default tools, consolidated (memory is one tool, not
# five). JAEGER_FULL_TOOLS=1 exposes the whole surface (debug/power use).
LEAN_CORE: frozenset[str] = frozenset({
    "execute_code", "terminal",
    "read_file", "write_file", "patch", "search_files", "list_skill_dir",
    "web_search", "web_extract",
    "memory",
    "todo", "clarify", "delegate_task", "board_add", "board_view", "list_skills",
    "computer_use", "browser",
    "vision_analyze", "image_generate", "text_to_speech",
})


# ``_lean_surface`` / ``model_visible`` lived here as a parallel
# visibility model — Hermes-style "lean-by-default with JAEGER_FULL_TOOLS
# as kill-switch". Nothing ever called them: every visibility check in
# the agent goes through :func:`tool_visible` below. Two competing
# models was a footgun, so the unused pair was removed. The lean-tool
# surface concept survives as the LEAN_CORE name set (used by the
# doctor's tool-registry check); the actual gate the agent uses is
# :func:`tool_visible`, opt-in via ``JAEGER_TOOLSET_SCOPING``.

# Built-in tool classes — loaded on demand via load_tools(name).
# Every registered tool should appear in EXACTLY ONE of these
# toolsets; intentional fail-open is reserved for the two meta-tools
# (``describe_tool`` / ``load_tools``) which are themselves in CORE.
# Classification is checked by ``test_every_registered_tool_is_classified``.
TOOLSETS: dict[str, frozenset[str]] = {
    "files": frozenset({
        # ``read_file`` and ``write_file`` are in CORE; the rest of
        # the file surface (patch, append, delete, search, list_dir,
        # move, copy) loads on intent.
        "append_file", "delete_file", "patch", "search_files",
        "list_skill_dir", "move_file", "copy_file",
    }),
    "code": frozenset({
        # ``execute_code`` is in CORE; heavy/risky code surfaces load
        # on intent (terminal, ssh, venv, dep install).
        "run_in_venv", "terminal", "remote_terminal",
        "install_package", "list_venv_packages",
    }),
    "media": frozenset({
        "text_to_speech", "listen", "vision_analyze", "image_generate",
        # fal.ai cloud generation (plugins/ai_gen) — the paid counterpart
        # to the local image_generate.
        "generate_image_fal", "generate_video_fal",
    }),
    "avatar": frozenset({
        # BETA — these register with ``beta=True``, so they reach the
        # agent only in dev mode (JAEGER_DEV_MODE=1 / --dev) while
        # Mochi is the animation testbed. Classified here so the
        # exhaustive-classification audit holds either way.
        "set_avatar_state", "play_timeline",
    }),
    "web": frozenset({
        # ``web_search`` and ``web_extract`` are in CORE; weather is
        # loadable so it doesn't bloat routing for chat-heavy users.
        "get_weather",
    }),
    "memory_granular": frozenset({
        # The pre-umbrella granular memory tools — kept registered so
        # historical callers and the bench corpus's expected_tools
        # entries still work, but hidden from default routing in
        # favour of the umbrella ``memory(action=…)`` (in CORE).
        "remember", "recall", "forget", "list_facts", "search_memory",
    }),
    "sessions": frozenset({"session_search"}),
    "board": frozenset({
        # board_add / board_view are CORE; the rest load on intent.
        "board_move", "board_update", "board_delete",
    }),
    # Multi-agent coordination (ported from hermes-agent). Deliberately a
    # SEPARATE toolset from ``board``: the board verbs are single-agent task
    # planning that any turn may reach for, while these are the worker /
    # orchestrator handoff protocol and stay off a normal chat turn's schema
    # entirely. They are additionally gated by ``kanban._kanban_mode``, so
    # loading the toolset is necessary but not sufficient.
    "kanban": frozenset({
        "kanban_show", "kanban_list", "kanban_create", "kanban_complete",
        "kanban_block", "kanban_unblock", "kanban_heartbeat",
        "kanban_comment", "kanban_link", "kanban_request_review",
        "kanban_request_changes", "kanban_attach", "kanban_attach_url",
        "kanban_attachments",
    }),
    "scheduling": frozenset({
        "schedule_prompt", "list_schedules", "cancel_schedule",
    }),
    "background": frozenset({
        "start_background", "list_background", "check_background",
        "stop_background", "pending_background", "open_on_host",
    }),
    "identity": frozenset({
        # Self-modifying tools — should never fire by accident on a
        # routine chat turn. Loadable explicitly when the user asks
        # the agent to update its name / soul.
        "set_name", "update_soul",
    }),
    "skills": frozenset({
        # Skill authoring + the Deep Think queue. ``skill`` umbrella
        # is in CORE; the lower-level operators load here.
        "reload_skills", "package_skill", "benchmark_skill",
        "propose_deep_think_task", "list_deep_think_queue",
        # Skill self-improvement: usage journal + the review trigger/toggle +
        # the revision log (feeds + records the Deep Think review loop).
        "skill_note", "skill_notes", "request_skill_review", "set_skill_review",
        "record_skill_revision",
        # Task-level after-action reflection (the REFLECT loop step).
        "reflect",
    }),
    "computer_use": frozenset({"computer_use", "browser"}),
    "credentials": frozenset({
        "get_credential", "list_credentials", "set_credential", "request_secret",
    }),
    "plugins": frozenset({"list_plugins", "setup_plugin", "activate_plugin", "send_message", "certify_admin"}),
    "email": frozenset({
        "send_email", "move_mail", "batch_move",
        "sweep_mail", "schedule_inbox_sweeper",
    }),
    "smart_home": frozenset({
        # Home Assistant plugin tools (jaeger_os/plugins/homeassistant) —
        # registered on import like send_message; loaded on intent.
        "ha_list_entities", "ha_get_state", "ha_list_services",
        "ha_call_service",
    }),
    "people": frozenset({"remember_person", "get_person", "list_people"}),
    "models": frozenset({"list_models", "download_model", "model_location",
                         "set_mode", "get_mode", "set_autonomy", "get_autonomy"}),
    "bench": frozenset({"run_benchmark"}),
    # ``self_check`` = the agent's doctor (same engine as `jaeger
    # doctor`); ``system_status`` = host cpu/disk/uptime.
    "diagnostics": frozenset({"system_status", "self_check", "diagnostics"}),
    # 0.9.3 MAC-NATIVE TOOL SUITE — one toolset per category, each also
    # feeding a persona_lane.py SELF_MODEL group (shortcuts/spotlight/
    # calendar) so the id knows it can reach for them.
    "shortcuts": frozenset({"list_shortcuts", "run_shortcut"}),
    "spotlight": frozenset({"spotlight_search"}),
    "calendar": frozenset({"get_events", "create_event"}),
    "contacts": frozenset({"lookup_contact"}),
    "clipboard": frozenset({"clipboard_read", "clipboard_write"}),
    "notifications": frozenset({"notify"}),
    "system_control": frozenset({"system_control"}),
    "media_control": frozenset({"media_control", "now_playing"}),
    "ocr": frozenset({"ocr_file"}),
}

# One-line description per built-in class — for the load_tools catalog.
TOOLSET_SUMMARY: dict[str, str] = {
    "files": "append, delete, patch, search files; list the workspace",
    "code": "shell/terminal, ssh, install packages, venv exec",
    "media": "text-to-speech, mic capture, vision, image/video generation (local + fal.ai cloud)",
    "avatar": "avatar face + animation timelines (BETA — dev mode only)",
    "web": "weather lookups (web_search / web_extract are always-on)",
    "memory_granular": "the pre-umbrella remember/recall/forget tools",
    "sessions": "search and inspect canonical conversation history",
    "board": "board_move / board_update / board_delete (board_add + board_view are CORE)",
    "kanban": "multi-agent worker/orchestrator protocol — claim, heartbeat, "
              "block, review, link and attach on shared board cards",
    "scheduling": "schedule, list, cancel cron prompts",
    "background": "long-running background processes; open URLs/apps",
    "identity": "set_name and update_soul — modify the agent's own identity",
    "skills": "reload, package, benchmark skills; deep-think queue",
    "computer_use": "Mac-driving + browser automation",
    "credentials": "list, read, and save stored credentials",
    "plugins": "list, set up + activate plugins; send messages",
    "email": "Mail.app writes: move_mail / batch_move / sweep_mail + send_email",
    "smart_home": "Home Assistant — list/read smart-home devices, call services",
    "people": "person index — profiles of people you know (name/likes/access)",
    "models": "list/download models; set_mode (normal/high/deep-sleep); "
              "set_autonomy (ask/scoped/auto)",
    "bench": "run the agent self-benchmark against the live pipeline",
    "diagnostics": "system health + cpu/disk status",
    "shortcuts": "list + run Shortcuts.app automations",
    "spotlight": "find files anywhere on the Mac by Spotlight metadata",
    "calendar": "read/create Calendar.app events",
    "contacts": "look up a person's email/phone in Contacts.app",
    "clipboard": "read/write the system clipboard",
    "notifications": "show a macOS notification banner",
    "system_control": "volume, brightness, dark mode, do-not-disturb, prevent-sleep",
    "media_control": "control + read Music.app/Spotify playback",
    "ocr": "extract text from an image or PDF (Vision framework)",
}

# ── Untrusted-content surface (ported from hermes-agent) ─────────────
#
# Ported from hermes-agent ``toolsets.py`` (``_HERMES_WEBHOOK_SAFE_TOOLS``,
# the ``hermes-webhook`` profile). hermes-agent is MIT licensed:
#
#   Copyright (c) 2025 Nous Research
#   Permission is hereby granted, free of charge, to any person obtaining
#   a copy of this software and associated documentation files (the
#   "Software"), to deal in the Software without restriction, including
#   without limitation the rights to use, copy, modify, merge, publish,
#   distribute, sublicense, and/or sell copies of the Software.
#
# Donor rationale, verbatim from that file: "Webhook events may originate
# from untrusted third-party content (for example, public PR titles/
# comments). Keep the default webhook toolset intentionally constrained
# to avoid local file/system execution by prompt injection."
#
# ADAPTATION. hermes-agent gates this by resolving a per-platform
# *profile* at schema-build time, because every entry point there picks a
# named toolset. Jaeger has no per-surface profile layer — visibility runs
# through :func:`tool_visible` — so the gate lives there instead, and it
# must hold under two Jaeger-specific conditions the donor never faced:
#
#   1. Toolset scoping is OFF by default here (``_scoping_enabled()``
#      returns False unless JAEGER_TOOLSET_SCOPING is set). A gate that
#      lived behind that flag would be inert in the default configuration,
#      which is precisely the configuration a webhook runs in.
#   2. Jaeger's scoping fails OPEN — an unclassified tool is visible. That
#      is the right default for a new built-in and the wrong one for
#      attacker-controlled input.
#
# So this gate is checked FIRST in ``tool_visible`` and fails CLOSED: in
# untrusted mode the answer is membership in UNTRUSTED_SAFE and nothing
# else. ``JAEGER_FULL_TOOLS`` does not lift it either — that switch exists
# for debugging a local session, not for re-opening an injection path.
UNTRUSTED_SAFE: frozenset[str] = frozenset({
    "web_search", "web_extract", "vision_analyze", "clarify",
})

# Deliberately NOT registered in TOOLSETS/TOOLSET_SUMMARY: membership
# there would make it reachable from ``load_tools``/``enable_toolset``,
# and a surface the model can name is a surface prompt injection can ask
# for. The meta-tools themselves (``load_tools``, ``describe_tool``,
# ``list_tools``) are CORE but not in UNTRUSTED_SAFE, so an untrusted turn
# cannot even enumerate what it is missing, let alone widen into it.
_untrusted: ContextVar[bool] = ContextVar("jaeger_untrusted_content", default=False)


def is_untrusted_content() -> bool:
    """True when this turn is processing attacker-controlled input."""
    return _untrusted.get()


def set_untrusted_content(value: bool) -> Token[bool]:
    """Mark the current context trusted/untrusted. Returns the reset token.

    Prefer :func:`untrusted_content` — this exists for callers that cross
    an async boundary and cannot hold a ``with`` block open.
    """
    return _untrusted.set(bool(value))


def reset_untrusted_content(token: Token[bool]) -> None:
    """Undo a :func:`set_untrusted_content` call."""
    _untrusted.reset(token)


@contextmanager
def untrusted_content() -> Iterator[None]:
    """Run a turn against the constrained surface.

    Wrap any ingress carrying third-party text — webhook payloads, PR
    titles and comments, scraped pages replayed into a turn::

        with untrusted_content():
            result = agent.run_turn(webhook_body)

    Nesting is safe, and the flag is a ContextVar, so a delegated child
    running in another task inherits it rather than silently escaping to
    the full surface.
    """
    token = _untrusted.set(True)
    try:
        yield
    finally:
        _untrusted.reset(token)


# Skill toolsets — populated at runtime by the skill loader. A skill is
# its own toolset; the loader records exactly what tools it registered.
_SKILL_TOOLSETS: dict[str, frozenset[str]] = {}
_SKILL_SUMMARY: dict[str, str] = {}

# MCP tools — re-exported from configured MCP servers at startup. Like a
# skill, a configured MCP server is deliberately loaded, so its tools
# are never lean-filtered out of the model's view.
_MCP_TOOLS: set[str] = set()


def register_mcp_tools(names: list[str]) -> None:
    """Record MCP tool names so the lean surface keeps them visible."""
    _MCP_TOOLS.update(n for n in (names or []) if n)

# Active extended toolsets for the session. Core is always implicitly on.
_active: set[str] = set()


def register_skill_toolset(name: str, tools: list[str],
                           summary: str = "") -> None:
    """Register a skill's tools as a named toolset. Called by the skill
    loader once per skill — the skill itself defines the membership."""
    name = (name or "").strip().lower()
    if not name or not tools:
        return
    _SKILL_TOOLSETS[name] = frozenset(tools)
    _SKILL_SUMMARY[name] = summary or f"the {name} skill"


def reset_toolsets() -> None:
    """Reset to core-only. Called at session start / instance switch."""
    _active.clear()


def enable_toolset(name: str) -> bool:
    """Make a toolset (built-in class or skill) visible. False if unknown.

    Refuses outright in untrusted-content mode: ``load_tools`` is the
    model-facing caller, so honouring a widening request there would let
    injected text talk its way back to the full surface one toolset at a
    time. The refusal is silent-by-return (False), matching the unknown-
    toolset case, so the model learns nothing about what it cannot reach.
    """
    if _untrusted.get():
        return False
    name = (name or "").strip().lower()
    if name in TOOLSETS or name in _SKILL_TOOLSETS:
        _active.add(name)
        return True
    return False


def active_toolset_names() -> set[str]:
    """The toolsets currently visible (``core`` always included)."""
    return {"core"} | _active


def all_toolsets() -> dict[str, str]:
    """Every loadable toolset → its one-line summary (built-ins + skills)."""
    return {**TOOLSET_SUMMARY, **_SKILL_SUMMARY}


def _members(toolset: str) -> frozenset[str]:
    return TOOLSETS.get(toolset) or _SKILL_TOOLSETS.get(toolset) or frozenset()


def tool_visible(name: str) -> bool:
    """Whether tool ``name`` is currently exposed to the model. With
    scoping OFF (the default), every tool is visible.

    The one exception is untrusted-content mode, which is checked before
    everything else and fails closed — see :data:`UNTRUSTED_SAFE`. It is
    deliberately ahead of the ``_scoping_enabled()`` early return and of
    the ``JAEGER_FULL_TOOLS`` escape hatch inside it: a webhook turn runs
    in the default configuration, where scoping is off, so a gate placed
    after that check would never fire on the path that needs it.
    """
    if _untrusted.get():
        return name in UNTRUSTED_SAFE
    if not _scoping_enabled():
        return True
    if name in CORE:
        return True
    for ts in _active:
        if name in _members(ts):
            return True
    # Fail-open: a tool that belongs to NO toolset is never hidden.
    in_any = (any(name in m for m in TOOLSETS.values())
              or any(name in m for m in _SKILL_TOOLSETS.values()))
    return not in_any
