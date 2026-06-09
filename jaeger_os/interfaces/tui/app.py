"""Jaeger-OS TUI app — REPL loop with hermes-agent-inspired chrome.

Parallel implementation to
:mod:`jaeger_os.instance.lilith.interfaces.tui.app`. Same
hermes-agent-shaped surface (banner / boot panel / slash commands /
status bar / ruminating spinner) so users get a consistent look
regardless of which instance they're driving.

The agent path boots through :func:`jaeger_os.main.boot_for_tui` —
the same instance resolve → manifest gate → lock → bind tools →
load model → prewarm flow ``python -m jaeger_os`` uses, minus the
cron runner and MCP/thinking extensions (the TUI keeps it minimal).
"""

from __future__ import annotations

import asyncio
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.padding import Padding
from rich.rule import Rule
from rich.text import Text

from jaeger_os import __version__ as JAEGER_VERSION

from .banner import JAEGER_ASCII, TAGLINE
from .ptk_input import CTRL_C, build_session, read_prompt
from .slash_commands import SlashContext, dispatch, is_slash
from .voice_session import is_exit_phrase
from .status import boot_panel, make_session_id
from .theme import ACCENT, ACCENT_BOLD, ACCENT_PTK


# Frames for the live "ruminating" spinner shown in the prompt_toolkit
# bottom toolbar while a turn runs on the worker thread.
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Queue sentinels. _WORKER_SHUTDOWN tells the turn worker to exit;
# "__deepthink__" as a turn source routes the worker into Deep Think.
_WORKER_SHUTDOWN = object()
_DEEPTHINK_SOURCE = "__deepthink__"

# Slash commands that swap the model / instance / pipeline out from
# under a turn — refused while one is running (Ctrl-C or wait first).
_TURN_UNSAFE_SLASH = frozenset({
    "model", "instance", "reboot", "shutdown", "factoryreset",
    "download", "deepthink",
})

_VOICE_BATCH_HEADER = (
    "Candidate voice input heard while I was busy. Decide with the "
    "voice gate whether these snippets were addressed to you. If they "
    "look like TV, ads, background conversation, or unrelated fragments, "
    "reply <ignore>:"
)


def _split_coalesced_voice(text: str) -> list[str]:
    """Return the original voice snippets from a coalesced prompt."""
    raw = (text or "").strip()
    if not raw:
        return []
    if not raw.startswith(_VOICE_BATCH_HEADER):
        return [raw]
    out = []
    for line in raw.splitlines()[1:]:
        line = line.strip()
        if line.startswith("- "):
            out.append(line[2:].strip())
    return [p for p in out if p]


def _format_coalesced_voice(phrases: list[str]) -> str:
    """Format one or more voice snippets as a single model turn."""
    clean = []
    for phrase in phrases:
        p = (phrase or "").strip()
        if p:
            clean.append(p)
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    bullets = "\n".join(f"- {p}" for p in clean)
    return f"{_VOICE_BATCH_HEADER}\n{bullets}"


def _kfmt(n: int) -> str:
    """Compact token count — Hermes's ``format_token_count_compact``
    (``agent/usage_pricing.py``) ported verbatim: K / M / B with smart
    precision (2 decimals < 10, 1 < 100, 0 otherwise) and trailing zeros
    stripped. ``27800 → '27.8K'``, ``980 → '980'``, ``1500000 → '1.5M'``.
    """
    abs_value = abs(int(n))
    if abs_value < 1_000:
        return str(int(n))
    sign = "-" if n < 0 else ""
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs_value >= threshold:
            scaled = abs_value / threshold
            if scaled < 10:
                text = f"{scaled:.2f}"
            elif scaled < 100:
                text = f"{scaled:.1f}"
            else:
                text = f"{scaled:.0f}"
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return f"{sign}{text}{suffix}"
    return str(int(n))


def _tool_label(tool: str) -> str:
    """A human-legible label for the ``┊`` activity line, so the user can
    follow what the agent is doing without knowing internal tool names.

    The computer-use tools get a platform + mode tag — that is the
    distinction the raw name hides: ``computer_bg_*`` drives the Mac
    *silently* via the Accessibility API (no cursor, no focus steal),
    while ``computer_*`` is the foreground path that operates the screen.
    A tool not matched here falls back to its raw name."""
    if tool.startswith("computer_bg_"):
        return f"🖥 macOS·background · {tool[len('computer_bg_'):]}"
    if tool.startswith("computer_"):
        return f"🖥 macOS·foreground · {tool[len('computer_'):]}"
    return tool


def _format_elapsed(seconds: float, *, live: bool = False, with_emoji: bool = False) -> str:
    """Hermes-faithful elapsed-time format (ported from
    ``_format_prompt_elapsed`` in ``hermes-agent/cli.py``). Keeps seconds
    visible at every scale so the value increments smoothly:

      ``59s → 1m → 1m 1s → 59m 59s → 1h → 1h 0m 1s → 23h 59m 59s → 1d``

    ``with_emoji=True`` prefixes ``⏱`` while the turn is live, ``⏲`` when
    frozen — width-1 glyphs so monospace alignment holds.
    """
    elapsed = max(0.0, float(seconds))
    days = int(elapsed // 86400)
    remaining = elapsed % 86400
    hours = int(remaining // 3600)
    remaining = remaining % 3600
    minutes = int(remaining // 60)
    secs = int(remaining % 60)
    if days > 0:
        time_str = f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        time_str = f"{hours}h {minutes}m {secs}s" if secs else f"{hours}h {minutes}m"
    elif minutes > 0:
        time_str = f"{minutes}m {secs}s" if secs else f"{minutes}m"
    else:
        time_str = f"{secs}s"
    if with_emoji:
        return f"{'⏱' if live else '⏲'} {time_str}"
    return time_str


# Hermes's ``_status_bar_context_style`` — context-percent → color band.
# < 50% healthy (green) · ≤ 80% warn (yellow) · ≤ 95% bad (red) · ≥ 95% critical.
def _pct_color(pct: int) -> str:
    if pct >= 95:
        return "fg:ansibrightred bold"
    if pct > 80:
        return "fg:ansired"
    if pct >= 50:
        return "fg:ansiyellow"
    return "fg:ansigreen bold"


# Typed phrases that enter continuous voice mode instead of being sent
# to the agent (which would otherwise call the one-shot `listen` tool).
# Gated on a short line so a coding request that merely mentions the
# microphone ("write code to turn on the mic") doesn't trip it.
_VOICE_TRIGGER_RE = re.compile(
    r"(turn on (the )?mic(rophone)?"
    r"|mic(rophone)? on\b"
    r"|enable (the )?mic(rophone)?"
    r"|voice (conversation|chat|mode)"
    r"|(start|enter|begin) voice"
    r"|have a voice (conversation|chat))",
    re.IGNORECASE,
)


def _wants_voice_mode(line: str) -> bool:
    """True when a typed line is a request to enter voice conversation."""
    line = (line or "").strip()
    return len(line) <= 80 and bool(_VOICE_TRIGGER_RE.search(line))


# 0.2.6: the prior _DEFAULT_INSTANCE_DIR hardcoded the pre-0.2.0
# bundled location at ``jaeger_os/instance/default/`` — a path INST-10
# removed and that no longer exists. The TUI fell back to it whenever
# no instance_dir was passed, which made ``./run.sh --instance NAME``
# silently land in a stale stub. Resolve dynamically through the
# canonical resolver instead so it tracks JAEGER_HOME +
# JAEGER_INSTANCE_NAME at call time.
def _default_instance_dir() -> Path:
    """Resolve the per-run default instance dir via the canonical
    resolver. Imported lazily so this module stays cheap to import
    in banner-only / test contexts."""
    from jaeger_os.core.instance.instance import (
        default_instance_name, resolve_instance_dir,
    )
    return Path(resolve_instance_dir(default_instance_name()))


# ── Permission confirmation ──────────────────────────────────────────


class _TuiConfirmationProvider:
    """Confirmation prompt for the concurrent TUI.

    A tier-gated tool (browser, run_shell, computer_use, …) asks the
    user for approval through this. The turn runs on a background worker
    thread, so this **cannot read stdin directly** — the main thread's
    live ``❯`` input line owns the terminal, and a competing
    ``input()`` from the worker simply never receives the keystrokes
    (the bug this class previously had: every answer came back empty, so
    every tier-gated tool auto-denied).

    The fix is hermes's approval-pipeline pattern: print the question,
    post a pending request, and **block on a threading.Event**. The REPL
    on the main thread routes the user's next typed line back as the
    answer and sets the Event — the answer travels through the input
    channel that actually works.

    Grants are **per skill** (:class:`~jaeger_os.core.safety.permissions.PermissionGrants`):
    *yes* approves the skill for the session, *always* persists it to
    ``<instance>/permissions.json``. An already-granted skill never
    re-prompts — answer *always* once and it is silent thereafter.
    """

    # A turn must never hang forever on an unattended prompt — after
    # this long with no answer, deny.
    _ANSWER_TIMEOUT_S = 300.0

    def __init__(self, tui: "JaegerTUI") -> None:
        from jaeger_os.core.safety.permissions import PermissionGrants
        self._tui = tui
        # 'yes' holds for the session, 'always' persists to
        # <instance>/permissions.json — loaded for the booted instance.
        self._grants = PermissionGrants.load(getattr(tui, "instance_dir", None))

    def confirm(self, request: Any) -> bool:
        skill = getattr(request, "skill", "") or ""
        if self._grants.is_granted(skill):
            return True
        # Non-interactive stdin (piped / the synchronous REPL) — there
        # is no live user to answer; fail safe, never block.
        if not sys.stdin.isatty():
            return False

        c = self._tui.console
        tier = getattr(request.tier, "name", str(request.tier))
        c.print()
        c.print(f"[bold yellow]⚠ permission needed[/]  "
                f"[cyan]{request.skill}.{request.operation}[/]  [dim]{tier}[/]")
        if request.summary:
            c.print(f"  [dim]{request.summary}[/]")
        c.print(f"  [bold]answer at the ❯ prompt:[/]  [bold]y[/]es "
                f"(this session)  ·  [bold]n[/]o  ·  [bold]a[/]lways "
                f"(remember [cyan]{skill or 'this'}[/])")

        # Post the request and block — the REPL wakes us with the answer.
        box: dict[str, Any] = {"event": threading.Event(), "answer": None}
        self._tui._pending_confirm = box
        try:
            answered = box["event"].wait(timeout=self._ANSWER_TIMEOUT_S)
        finally:
            self._tui._pending_confirm = None

        if not answered:
            c.print("  [dim]✗ no answer — denied.[/]")
            return False
        ans = (box["answer"] or "").strip().lower()
        # First-letter match: "always"/"allow"/"a" persist the grant;
        # "yes"/"y" grant it for the session; anything else denies.
        if ans.startswith("a"):
            self._grants.grant_persistent(skill)
            c.print(f"  [green]✓ remembered[/] — [cyan]{skill or 'this'}[/] "
                    f"won't ask again")
            return True
        if ans.startswith("y"):
            self._grants.grant_session(skill)
            return True
        c.print("  [dim]✗ denied.[/]")
        return False


# ── App ──────────────────────────────────────────────────────────────


class JaegerTUI:
    """The interactive TUI driver for Jaeger-OS.

    Owns the Rich Console, the agent (lazy-built on first turn so
    `--banner-only` is cheap), the slash-command context, and the
    session counters. Mirrors :class:`lilith.interfaces.tui.app.LilithTUI`.
    """

    def __init__(
        self,
        *,
        instance_dir: Path | None = None,
        model_name: str = "gemma-4-26B-A4B-it",
        version: str = JAEGER_VERSION,
        skip_model: bool = False,
    ) -> None:
        self.console = Console()
        self.instance_dir = instance_dir or _default_instance_dir()
        self.model_name = model_name
        self.version = version
        self.session_id = make_session_id()
        self.skip_model = skip_model
        self._agent = None
        self._client = None
        self._boot = None  # TUIBootResult from jaeger_os.main.boot_for_tui
        self._voice: Any = None  # VoiceController — the always-on mic, or None
        self._ptk_session: Any = None  # prompt_toolkit PromptSession (lazy)
        self._statusbar_on = True  # bottom status bar visible (/statusbar)
        # G4 minimal (operator-locked 2026-06-07): the conversation pane
        # gets drowned by [heard] / [skipped] / gate-status prints during
        # noisy environments (TV / movies playing in background).
        # `/quiet on` mutes those prints; `_voice_activity_log` keeps the
        # last N events buffered so `/quiet` status reporting can show
        # what was muted.  Full split-screen Live + Layout deferred —
        # see dev_docs/0.4.0_voice_gate_unification_prompt.md G4 section.
        # Default ON: most operators don't want to see "[skipped —
        # non-speech: '(wind blowing)']" / "[skipped — non-speech:
        # '[BLANK_AUDIO]']" cluttering the conversation pane during
        # noisy environments.  /quiet off reveals voice activity for
        # debug.  Operator-flipped 2026-06-07 after live testing
        # showed background-noise spam dominated the UI.
        self._quiet_voice = True  # /quiet toggle (default hidden)
        from collections import deque as _deque
        self._voice_activity_log: _deque = _deque(maxlen=30)
        # Aggregation: consecutive non-speech skips collapse to one
        # entry with a counter ("[skipped — 5 non-speech events]")
        # instead of N lines of the same skip.
        self._last_voice_event_was_non_speech = False
        self._consecutive_non_speech_count = 0
        self._started_at = time.perf_counter()
        self._context_tokens = 0
        self._context_max = 8192
        self._last_turn_s = 0.0   # wall time of the most recent turn
        self._turn_count = 0      # turns run this session (for /usage)
        self._last_answer = ""    # most recent reply text (for /copy)
        # ── Concurrent turn worker (hermes-style: type while it works) ──
        # Turns run on a background thread so the input line stays live.
        self._turn_queue: queue.Queue = queue.Queue()
        self._turn_running = threading.Event()   # set while a turn executes
        self._voice_queue_lock = threading.Lock()
        self._worker_stop = threading.Event()    # signals the worker to exit
        self._worker: threading.Thread | None = None
        self._turn_started_at = 0.0              # for the live toolbar timer
        self._current_activity = ""             # live spinner label
        self._busy_mode = "interrupt"           # /busy: interrupt|queue|steer
        # A tier-gated tool blocked on a y/n/a answer — the REPL routes
        # the user's next line here. None when nothing is waiting.
        self._pending_confirm: dict | None = None
        self._ptk_loop: Any = None              # prompt_toolkit's asyncio loop
        self._last_activity = time.monotonic()  # for auto-idle Deep Think
        self._idle_fired = False
        self._voice_thread: threading.Thread | None = None
        self._voice_stop = threading.Event()
        self.slash_ctx = SlashContext(
            console=self.console,
            instance_dir=self.instance_dir,
            tui=self,  # let /instance <name> + /download reach back here
        )

    # ── Boot screen ─────────────────────────────────────────────────

    def render_boot(self) -> None:
        """Print the banner + tagline + boot status panel. One-shot."""
        self.console.print(Text(JAEGER_ASCII, style=ACCENT_BOLD))
        self.console.print(Text(TAGLINE, style=f"dim {ACCENT}"))
        self.console.print()
        self.console.print(boot_panel(
            version=self.version,
            instance_name=self.instance_dir.name,
            model_name=self.model_name,
            session_id=self.session_id,
            instance_dir=self.instance_dir,
        ))
        self.console.print()

    def _print_ready_hint(self) -> None:
        """The 'type a prompt' hint. Printed *after* the eager boot so it
        only appears once the Jaeger is actually operational — not while
        the model is still loading."""
        self.console.print(
            "[dim]Type a prompt, or [bold]/help[/] for slash commands.[/]"
        )
        self.console.print()

    # ── Agent (lazy) ────────────────────────────────────────────────

    def _ensure_agent(self) -> Any:
        """Boot the jaeger pipeline on first use. Cached for the
        lifetime of the TUI; cleanup runs in :meth:`repl`'s finally."""
        if self._client is not None or self.skip_model:
            return self._client
        from jaeger_os.main import boot_for_tui

        with self.console.status(
            f"[{ACCENT_BOLD}]booting jaeger…[/]", spinner="dots",
        ):
            self._boot = boot_for_tui(instance_name=self.instance_dir.name)
        self._client = self._boot.client
        # Refresh status panel state with what the pipeline picked
        # (the instance dir may have been wizard-created on first run;
        # the brain may be an external model rather than local Gemma).
        self.instance_dir = self._boot.layout.root
        self.model_name = getattr(self._client, "model_name", self.model_name)
        self._install_confirmations()
        return self._client

    def _install_confirmations(self) -> None:
        """Install the permission confirmation provider for the TUI.

        'confirm' mode → the spinner-aware prompt; 'allow' mode →
        auto-approve. The mode is ``config.permissions.mode``, chosen at
        first-boot setup and persisted, so the posture survives restarts."""
        from jaeger_os.core.safety.permissions import (
            AllowAllProvider, PermissionPolicy, install_policy,
        )
        from jaeger_os.main import _pipeline
        cfg = _pipeline.get("config")
        mode = getattr(getattr(cfg, "permissions", None), "mode", "confirm")
        provider = (AllowAllProvider() if mode == "allow"
                    else _TuiConfirmationProvider(self))
        install_policy(PermissionPolicy(confirmation=provider))
        # Live tool-progress: the agent loop calls this per tool call so
        # the TUI can show ``┊`` activity lines + the toolbar spinner.
        _pipeline["tool_event_cb"] = self._on_tool_event

    def _boot_eager(self) -> None:
        """Boot the pipeline at launch so the Jaeger is operational the
        moment the prompt appears — no waiting for the first message to
        trigger the model load + warmups.

        A failure here is non-fatal: it is printed and ``_ensure_agent``
        will retry on the first turn, so a transient boot error never
        leaves the user staring at a dead REPL."""
        if self.skip_model:
            return
        try:
            self._ensure_agent()
        except Exception as exc:  # noqa: BLE001
            self.console.print(
                f"[red]Boot failed:[/] {exc}\n"
                "[dim]Will retry on your first message.[/]"
            )
            return
        # Voice is on by default — a Jaeger is embodied and always
        # listens. Bring the mic up now so it's live the instant the
        # prompt appears. A failure here is non-fatal (text still works).
        try:
            if self._voice_config().enabled:
                self.start_voice()
        except Exception as exc:  # noqa: BLE001
            self.console.print(f"[dim](voice didn't start: {exc})[/]")

    def switch_instance(self, name: str) -> None:
        """Hot-switch the running TUI to a different instance.

        Tears down the current llama-cpp client + instance lock, then
        boots ``name`` via :func:`boot_for_tui`. Wall cost is ~5-10s
        (Gemma reload). Called by ``/instance <name>``; raises on any
        boot error so the slash handler can surface it."""
        import gc

        from jaeger_os.main import boot_for_tui
        from .status import make_session_id

        # Release current boot before allocating the new one. On
        # unified-memory Macs we MUST drop the prior llama-cpp client
        # first or peak RSS doubles for a moment.
        if self._boot is not None:
            try:
                self._boot.cleanup()
            except Exception:
                pass
        self._boot = None
        self._client = None
        self._agent = None
        gc.collect()

        # Boot the new instance. Any failure propagates so the slash
        # handler can print it and the user can pick another instance.
        self._boot = boot_for_tui(instance_name=name)
        self._client = self._boot.client
        self.instance_dir = self._boot.layout.root
        self.model_name = getattr(self._client, "model_name", self.model_name)
        self._install_confirmations()
        self.session_id = make_session_id()
        # Slash context carries instance_dir — rebuild so /facts, /instance,
        # etc. see the new path. ``tui=self`` preserved so further
        # switches still work.
        self.slash_ctx = SlashContext(
            console=self.console,
            instance_dir=self.instance_dir,
            tui=self,
        )

    # ── Turn ────────────────────────────────────────────────────────

    def run_turn(self, user_text: str, *, source: str = "text") -> None:
        """Run one user turn — interruptibly.

        A turn no longer locks up the TUI: **Ctrl-C aborts the turn**
        (and returns to the prompt instead of quitting), and in a voice
        turn **speaking aborts it too** — the agent loop checks a cancel
        flag between steps and halts gracefully. ``source`` is "text"
        or "voice"."""
        client = self._ensure_agent()
        if client is None:
            self.console.print(
                "[yellow]Agent not initialized (skip_model=True).[/]"
            )
            return

        from jaeger_os.main import begin_turn_cancel_scope, request_turn_cancel

        cancel = begin_turn_cancel_scope()
        # Voice turn: sustained user speech during the turn trips the
        # cancel flag, so the user can talk over a long 'ruminating'.
        armed = (source == "voice" and self._voice is not None
                 and self._voice.running)
        if armed:
            self._voice.arm_interrupt(cancel)
        try:
            if source == "voice":
                self._run_voice_turn(client, user_text)
            else:
                self._run_text_turn(client, user_text, source=source)
        except KeyboardInterrupt:
            # Ctrl-C aborts THIS turn, not the whole TUI. Setting the
            # flag too lets the agent loop unwind cleanly when it is
            # between steps rather than mid-decode.
            request_turn_cancel()
            self.console.print("\n[yellow]⨯ stopped — back to you.[/]")
        finally:
            if armed:
                self._voice.disarm_interrupt()

    # ── Turn chrome (hermes-style) ──────────────────────────────────

    def _agent_name(self) -> str:
        """The instance's display name for the answer-panel title.
        Read live from identity.yaml so a mid-session `set_name` shows
        up immediately; falls back to 'Jaeger'."""
        return self._resolve_instance_name() or "Jaeger"

    def _log_voice(self, message: str, *, kind: str = "info") -> None:
        """Route a voice-activity message through the /quiet filter +
        consecutive-non-speech aggregation, then maybe print it.

        ``kind`` classifies the event:
          ``"heard"``       — STT finalized a phrase (white)
          ``"skipped"``     — non-speech marker dropped (dim, aggregated)
          ``"gate_accept"`` — LLM gate let it through (green)
          ``"gate_ignore"`` — LLM gate suppressed (yellow)
          ``"info"``        — coalesce note, self-speech-filter, etc.

        Consecutive ``"skipped"`` events collapse to one line with a
        counter — the operator explicitly asked not to see "a long
        continouse skipped list of status."
        """
        # Track in the buffer regardless of /quiet — operator might
        # flip quiet off and want to know what they missed.
        self._voice_activity_log.append((kind, message))
        if self._quiet_voice:
            return

        # Aggregate consecutive skips.  Print the FIRST skip immediately,
        # subsequent ones increment an inline counter line that we
        # re-print as a single replacement.  Without raw terminal
        # control we approximate this by just printing a count when
        # the streak ends OR every 5 skips so the user knows skips
        # are still happening.
        if kind == "skipped":
            self._consecutive_non_speech_count += 1
            if not self._last_voice_event_was_non_speech:
                # First in a streak — show it normally.
                self.console.print(message)
                self._last_voice_event_was_non_speech = True
            elif self._consecutive_non_speech_count % 5 == 0:
                # Every 5th in a streak — show a count summary.
                self.console.print(
                    f"[dim](+{self._consecutive_non_speech_count} "
                    f"non-speech events skipped)[/]"
                )
            return

        # Non-skip event: if we were in a non-speech streak, flush a
        # final count summary before rendering.
        if self._last_voice_event_was_non_speech and \
                self._consecutive_non_speech_count > 1:
            self.console.print(
                f"[dim](… {self._consecutive_non_speech_count} non-speech "
                "events skipped)[/]"
            )
        self._last_voice_event_was_non_speech = False
        self._consecutive_non_speech_count = 0
        self.console.print(message)

    def _render_turn_header(self, user_text: str, *, source: str = "text") -> None:
        """The hermes-style turn separator — the user's message framed
        between two rules, on a bullet line (● typed, 🎙 spoken, ◎ goal).

        Built with :class:`Text.append` rather than Rich markup so a
        message containing ``[red]`` etc. can never inject styling."""
        self.console.print()
        self.console.print(Rule(style=ACCENT))
        glyph = {"voice": "🎙", "goal": "◎",
                 "kanban_idle": "◇"}.get(source, "●")
        line = Text("  ")
        line.append(f"{glyph} ", style=ACCENT_BOLD)
        line.append(user_text.strip(), style="bold")
        self.console.print(line)
        self.console.print(Rule(style=ACCENT))

    def _render_answer(self, text: str, *, error: str | None = None) -> None:
        """Render the agent's reply hermes-style: a left-labelled top
        rule, the body indented into the chat column, a closing rule.

        Tool activity is shown live *during* the turn (see
        :meth:`_on_tool_event`), not here. The body is rendered via
        :class:`rich.markdown.Markdown` for the success path (so the
        model's ``**bold**`` / bullets / headers render as the user
        expects) and as a plain :class:`Text` for the error path (so
        an LMStudio HTTP error body that contains ``[red]`` style
        sequences is never mis-interpreted as Rich markup).

        ``rich.markdown.Markdown`` escapes Rich-style ``[tag]`` syntax
        before rendering — it's the safe-AND-pretty option compared to
        a raw :class:`Text` wrap.
        """
        body = (error or text or "").strip()
        if not body:
            return
        is_err = error is not None
        if is_err:
            # Recognise common model-server failures and surface a clear,
            # actionable hint instead of the raw HTTP body.
            from jaeger_os.core.runtime.cloud_errors import friendly_error_text
            body = friendly_error_text(body, model_name=self.model_name)
        else:
            self._last_answer = body   # for /copy
        accent = "red" if is_err else ACCENT
        label = Text(f" ✦ {'error' if is_err else self._agent_name()} ",
                     style=f"bold {accent}")
        self.console.print()
        self.console.print(Rule(label, align="left", style=accent))
        self.console.print()
        if is_err:
            renderable = Text(body, style="red")
        else:
            # Markdown renderer handles **bold** / lists / headers / code
            # blocks; escapes Rich ``[tag]`` markup so a literal "[red]"
            # in the model's answer is shown, not interpreted.
            from rich.markdown import Markdown
            renderable = Markdown(body, code_theme="monokai")
        self.console.print(Padding(renderable, (0, 2, 0, 4)))
        self.console.print()
        self.console.print(Rule(style=accent))

    # ── Live tool activity (during a turn) ──────────────────────────

    def _on_tool_event(self, phase: str, tool: str, detail: str,
                       elapsed: float) -> None:
        """Agent-loop callback — fired as a turn runs, once per tool.

        ``phase`` is "start" or "done". On start the bottom-toolbar
        spinner switches to the tool name; on done a ``┊`` activity line
        is printed into the scrollback with the elapsed time, hermes-
        style. Runs on the turn worker thread — the print scrolls above
        the live input line via ``patch_stdout``."""
        label = _tool_label(tool)
        if phase == "start":
            self._current_activity = label
            return
        # phase == "done"
        self._current_activity = "ruminating"
        from jaeger_os.main import _pipeline
        if not _pipeline.get("show_tool_activity", True):
            return
        line = Text("  ┊ ", style=ACCENT)
        line.append("🔧 ", style="")
        line.append(label, style="cyan")
        if detail:
            line.append(f"  {detail}", style="dim")
        if elapsed > 0:
            line.append(f"  {elapsed:.1f}s", style="dim")
        self.console.print(line)

    def _current_ctx_max(self) -> int:
        """Active context-window size for the status-bar gauge denominator.

        Prefers the *loaded* model client's actual ``n_ctx`` so the
        denominator matches what's really allocated — for llama-cpp-python
        builds that also expose ``native_ctx_max``, we still surface the
        loaded value because that's the hard ceiling for the running
        process. Falls back to ``config.model.ctx`` (the wizard value)
        when the client hasn't recorded it yet, then to the cached
        ``_context_max`` (or 8192) when the pipeline isn't ready."""
        try:
            from jaeger_os.main import _pipeline
            client = _pipeline.get("client")
            loaded = int(getattr(client, "loaded_ctx", 0) or 0)
            if loaded > 0:
                self._context_max = loaded
                return loaded
            cfg = _pipeline.get("config")
            ctx = int(getattr(getattr(cfg, "model", None), "ctx", 0) or 0)
            if ctx > 0:
                self._context_max = ctx
                return ctx
        except Exception:  # noqa: BLE001
            pass
        return self._context_max or 8192

    def _current_native_ctx_max(self) -> int | None:
        """The model's *trained* native max context (n_ctx_train for
        llama-cpp-python). Used by the ``/runtime`` panel to flag a
        loaded ctx that's well below the model's capability — e.g.
        Qwen3-Coder-30B-A3B at 262K loaded as 16K. ``None`` means the
        client doesn't expose it."""
        try:
            from jaeger_os.main import _pipeline
            client = _pipeline.get("client")
            native = int(getattr(client, "native_ctx_max", 0) or 0)
            return native or None
        except Exception:  # noqa: BLE001
            return None

    def _refresh_context_estimate(self) -> None:
        """Update the context-token gauge from the session-history size
        — a chars/4 estimate. Rough, but it moves the bottom-bar gauge
        as the conversation grows, which is what the gauge is for.

        Reads from TWO storage locations and concatenates them:

          1. ``_session_histories[session_key]`` — the legacy
             pydantic-ai history (``msg.parts[].content``). Empty for
             Phase-9 sessions but still walked for hybrid mode.
          2. ``_jaeger_agents_by_session[session_key].messages`` — the
             Phase-9 ``JaegerAgent`` instance's internal list of
             TypedDict messages. This is where the live conversation
             actually lives.

        The gauge was stuck at 0% in 0.1.0 because we only walked #1,
        which is empty for the new agent path.

        Plus the system-prompt prefix + tool-schema blob — those are
        what the model ACTUALLY sees per turn, so the gauge that
        leaves them out underestimates and lulls the operator into
        thinking they have plenty of headroom when in fact they're
        sitting ~3-15K tokens deep before the first user message.
        """
        chars = 0
        history: list = []
        try:
            from jaeger_os.main import (
                _DEFAULT_SESSION_KEY, _get_session_history, _pipeline,
            )
            history = list(_get_session_history(_DEFAULT_SESSION_KEY) or [])
            # Phase-9 JaegerAgent (preferred source for current sessions).
            agents = _pipeline.get("jaeger_agents_by_session") if isinstance(
                _pipeline.get("jaeger_agents_by_session"), dict
            ) else None
            if agents is None:
                # Fall back to the private module attribute — names match
                # what main.py uses today.
                try:
                    from jaeger_os.main import _jaeger_agents_by_session
                    agents = _jaeger_agents_by_session
                except Exception:  # noqa: BLE001
                    agents = {}
            agent = (agents or {}).get(_DEFAULT_SESSION_KEY)
            if agent is not None and hasattr(agent, "messages"):
                history = history + list(agent.messages or [])
            # Add the system prompt prefix — it's a fixed cost per turn
            # but the gauge should reflect that the budget isn't all
            # "free" at the start of a session.
            sysprompt = _pipeline.get("system_prompt") or ""
            chars += len(str(sysprompt))
            # Tool schemas — the other big fixed cost. We estimate by
            # summing the JSON-serialised schema for every currently
            # visible tool. Cheap enough to recompute per refresh.
            try:
                from jaeger_os.agent.schemas.tool_registry import get_tools
                from jaeger_os.core.skills.toolsets import tool_visible
                import json as _json2
                for t in get_tools():
                    if tool_visible(t.name) and hasattr(t, "to_openai_schema"):
                        chars += len(_json2.dumps(t.to_openai_schema(),
                                                   ensure_ascii=False))
            except Exception:  # noqa: BLE001 — never block the gauge
                pass
        except Exception:  # noqa: BLE001
            return
        import json as _json
        for msg in history:
            # ── Phase-9 dict-shape Message ─────────────────────────
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    chars += len(content)
                elif content is not None:
                    chars += len(_json.dumps(content, default=str))
                for tc in (msg.get("tool_calls") or []):
                    args = tc.get("arguments") if isinstance(tc, dict) else None
                    if args is not None:
                        try:
                            chars += len(_json.dumps(args, default=str))
                        except (TypeError, ValueError):
                            chars += len(str(args))
                    name = tc.get("name") if isinstance(tc, dict) else ""
                    if name:
                        chars += len(str(name))
                continue
            # ── Legacy pydantic-ai message ─────────────────────────
            for part in getattr(msg, "parts", []) or []:
                content = getattr(part, "content", None)
                if content:
                    chars += len(str(content))
        self._context_tokens = chars // 4
        try:
            cfg = _pipeline.get("config")
            ctx = int(getattr(getattr(cfg, "model", None), "ctx", 0) or 0)
            if ctx > 0:
                self._context_max = ctx
        except Exception:  # noqa: BLE001
            pass

    def _run_text_turn(
        self, client: Any, user_text: str, *, source: str = "text",
    ) -> None:
        """A typed (or goal-loop) turn — runs the unified turn and
        renders the reply in hermes-style chrome (rule-framed user
        message, live ``┊`` tool lines, the answer in a labelled box).

        The "ruminating" spinner + live counters live in the
        prompt_toolkit bottom toolbar (see :meth:`_bottom_toolbar`), not
        a Rich ``Live`` — a ``Live`` on this worker thread would fight
        the input line the main thread renders. ``source`` is "text" or
        "goal"."""
        from jaeger_os.main import _DEFAULT_SESSION_KEY, run_for_voice

        self._render_turn_header(user_text, source=source)
        started = time.perf_counter()
        # Expand @file / @url references — the header above shows the
        # concise original; the agent receives the inlined content (A4).
        try:
            from jaeger_os.agent.prompts.context_refs import expand_references
            agent_text = expand_references(user_text)
        except Exception:  # noqa: BLE001 — never let expansion break a turn
            agent_text = user_text
        result = run_for_voice(client, agent_text,
                               session_key=_DEFAULT_SESSION_KEY)
        self._last_turn_s = time.perf_counter() - started
        self._turn_count += 1
        self._refresh_context_estimate()
        self._render_answer(result.get("text") or "",
                            error=result.get("error"))

    # ── Voice conversation ──────────────────────────────────────────

    def _resolve_instance_name(self) -> str | None:
        """The instance's display name (identity.yaml ``name``) — used as
        the voice wake word. None on any read error."""
        try:
            from jaeger_os.core.instance.instance import InstanceLayout
            from jaeger_os.core.instance.schemas import Identity, load_yaml
            layout = InstanceLayout(root=self.instance_dir)
            return load_yaml(layout.identity_path, Identity).name
        except Exception:  # noqa: BLE001
            return None

    def _voice_config(self) -> Any:
        """The active instance's VoiceConfig, read from the live pipeline
        config. Falls back to defaults (all on) if it can't be read."""
        from jaeger_os.core.instance.schemas import VoiceConfig
        try:
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            return getattr(cfg, "voice", None) or VoiceConfig()
        except Exception:  # noqa: BLE001
            return VoiceConfig()

    def start_voice(self, *, announce: bool = True) -> None:
        """Bring the always-on mic online from the current VoiceConfig.
        No-op if it is already running; prints the reason if it can't."""
        if self._voice is not None and self._voice.running:
            if announce:
                self.console.print("[dim]🎙  mic is already on.[/]")
            return
        vc = self._voice_config()
        from .voice_session import VoiceController
        self._voice = VoiceController(
            self.console,
            wake_word=vc.wake_word,
            follow_up=vc.follow_up,
            barge_in=vc.barge_in,
            follow_up_seconds=vc.follow_up_seconds,
            wake_name=self._resolve_instance_name(),
            llm_gate=getattr(vc, "llm_gate", True),
            pending_turn_max_age_s=getattr(
                vc, "pending_turn_max_age_s", 3.0,
            ),
            # Forward AudioSession's GateDecision events through the
            # TUI's voice-activity log so /quiet + non-speech
            # aggregation apply uniformly.  The node publishes the
            # decisions; this is the operator-facing render path.
            on_voice_activity=self._log_voice,
        )
        if announce:
            self.console.print("[dim]🎙  bringing the mic online…[/]")
        if not self._voice.start():
            self._voice = None
            return
        # Spawn the mic poller so each committed phrase becomes a turn,
        # routed through the same busy-input rules as a typed line.
        self._voice_stop.clear()
        self._voice_thread = threading.Thread(
            target=self._voice_poll_loop, name="jaeger-voice", daemon=True)
        self._voice_thread.start()
        if announce:
            self._print_voice_banner()

    def _print_voice_banner(self) -> None:
        """One-line 'voice is on, here's how to use it' notice."""
        v = self._voice
        if v is None:
            return
        if v.wake_word:
            msg = (f"[bold green]🎙  voice on[/] — always listening. Say "
                   f"[bold]\"{v.wake_word_phrase}\"[/] to talk, or just type.")
        else:
            msg = ("[bold green]🎙  voice on[/] — always listening, no wake "
                   "word. Talk or type at any time.")
        if v.barge_in and not v.barge_in_live:
            msg += ("\n[dim](barge-in wanted but speexdsp is missing — the "
                    "mic pauses while I speak.)[/]")
        self.console.print(msg)

    def stop_voice(self) -> None:
        """Shut the mic down — poll thread first, then the controller.
        Idempotent; safe to call from the poll thread itself."""
        self._voice_stop.set()
        t = self._voice_thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2.0)
        self._voice_thread = None
        if self._voice is not None:
            self._voice.stop()
            self._voice = None

    def apply_voice_setting(self, key: str, value: bool) -> str:
        """Toggle a voice setting, persist it to config.yaml, and apply
        it live (restarting the mic when the change needs a rebuild).
        Returns a short status line for the slash handler to print."""
        vc = self._voice_config()
        if key not in {"enabled", "wake_word", "follow_up", "barge_in"}:
            return f"[yellow]Unknown voice setting '{key}'.[/]"
        setattr(vc, key, value)
        self._persist_voice_config(vc)
        if key == "enabled":
            if value:
                self.start_voice()
            else:
                self.stop_voice()
        elif self._voice is not None and self._voice.running:
            # wake_word / barge_in are fixed when the STT is built;
            # follow_up is cheap but restart anyway for one clean path.
            self.stop_voice()
            self.start_voice()
        return f"[green]voice.{key}[/] → {'on' if value else 'off'}"

    def _persist_voice_config(self, vc: Any) -> None:
        """Write the VoiceConfig into the live config and config.yaml."""
        try:
            from jaeger_os.core.instance.instance import InstanceLayout
            from jaeger_os.core.instance.schemas import dump_yaml
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            if cfg is None:
                return
            cfg.voice = vc
            dump_yaml(InstanceLayout(root=self.instance_dir).config_path, cfg)
        except Exception as exc:  # noqa: BLE001
            self.console.print(
                f"[dim](couldn't persist voice settings: {exc})[/]"
            )

    def voice_status_text(self) -> str:
        """Render the current voice settings for `/voice` with no args."""
        vc = self._voice_config()
        live = self._voice is not None and self._voice.running

        def b(x: bool) -> str:
            return "[green]on[/]" if x else "[dim]off[/]"

        return "\n".join([
            f"[bold]Voice[/] — mic is "
            f"{'[green]live[/]' if live else '[dim]off[/]'}",
            f"  enabled    {b(vc.enabled)}   [dim]/voice on│off[/]",
            f"  wake word  {b(vc.wake_word)}   [dim]/voice wake on│off[/]",
            f"  follow-up  {b(vc.follow_up)}   [dim]/voice followup on│off[/]",
            f"  barge-in   {b(vc.barge_in)}   [dim]/voice bargein on│off[/]",
        ])

    def _run_voice_turn(self, client: Any, user_text: str) -> None:
        """A spoken turn: run the unified turn, render the same
        hermes-style chrome a typed turn gets, then speak the reply
        (barge-in aware) and open the follow-up window.

        2026-06-07 perf-corrected single-pass gate:
        AudioSession owns the FAST deterministic filters (non-speech
        marker + self-speech) — phrases that fail those are dropped
        before they ever reach this method.  The LLM <ignore>/<reply>
        gate runs INSIDE the brain's normal turn — it's the response
        prefix.  We parse the leading tag here with parse_gate().
        ``<ignore>`` → suppress speech + rendering;
        ``<reply>foo`` → strip tag, render + speak ``foo``.

        Why this isn't separate gate calls: a separate gate prompt
        would invalidate the brain's KV cache and trigger a cold
        prefill on every turn (measured 50× slowdown in
        dev_benchmark/voice_gate_latency.py).  Single-pass is one
        LLM call per phrase; the gate decision is the response's
        first 30 chars.
        """
        # Toggle the follow-up addressed_hint env var BEFORE the
        # turn runs so the prompt assembler appends the permissive
        # clause when we're in conversation continuation.
        import os as _os
        v = self._voice
        in_followup = bool(v is not None and v.running
                           and getattr(v, "in_followup_window", lambda: False)())
        if in_followup:
            _os.environ["JAEGER_VOICE_ACTIVE_FOLLOWUP"] = "1"
        else:
            _os.environ.pop("JAEGER_VOICE_ACTIVE_FOLLOWUP", None)

        from jaeger_os.core.voice import (
            clean_voice_reply,
            is_non_speech_marker,
        )
        from jaeger_os.main import _DEFAULT_SESSION_KEY, run_for_voice

        self._render_turn_header(user_text, source="voice")
        started = time.perf_counter()
        result = run_for_voice(
            client,
            user_text,
            session_key=_DEFAULT_SESSION_KEY,
        )
        self._last_turn_s = time.perf_counter() - started
        self._turn_count += 1
        self._refresh_context_estimate()
        # _run_turn now strips the <reply> tag and exposes
        # voice_gate_ignored=True when the brain emitted <ignore>.
        # No need to re-parse here; just honor the flag.
        if result.get("voice_gate_ignored"):
            self._log_voice(
                "[dim]🤫 voice gate: ignored (brain emitted <ignore>)[/]",
                kind="gate_ignore",
            )
            return
        text = clean_voice_reply(result.get("text") or "")
        if text and is_non_speech_marker(text):
            self._log_voice(
                f"[dim]🤫 suppressed non-speech voice reply: {text!r}[/]",
                kind="gate_ignore",
            )
            return
        self._render_answer(text, error=result.get("error"))
        v = self._voice
        if v is not None and v.running:
            if text and not result.get("spoke_via_tool"):
                v.speak(text)
            v.chime("followup")
            v.open_followup()

    # ── Goal loop ───────────────────────────────────────────────────

    def _session_transcript_tail(self, max_chars: int = 4000) -> str:
        """Serialize the recent session history into a plain-text
        transcript the goal evaluator can read. Pulls from the same
        ``cli`` session key ``run_command`` writes to."""
        from jaeger_os.main import _DEFAULT_SESSION_KEY, _get_session_history
        try:
            history = _get_session_history(_DEFAULT_SESSION_KEY)
        except Exception:
            return ""
        lines: list[str] = []
        for msg in history[-14:]:
            for part in getattr(msg, "parts", []):
                pk = getattr(part, "part_kind", None)
                content = getattr(part, "content", None)
                if pk == "user-prompt" and content:
                    lines.append(f"User: {content}")
                elif pk == "text" and content:
                    lines.append(f"Assistant: {content}")
                elif pk == "tool-return":
                    tn = getattr(part, "tool_name", "tool")
                    lines.append(f"[{tn} result]: {str(content)[:200]}")
        return "\n".join(lines)[-max_chars:]

    def _post_turn_goal_check(self) -> str | None:
        """After a turn, evaluate the active goal. Returns the prompt
        for the next auto-fired turn, or None when there's no goal /
        the goal is met / the iteration cap is hit."""
        from jaeger_os.main import clear_goal, evaluate_goal, get_goal

        goal = get_goal()
        if goal is None or goal.achieved:
            return None
        transcript = self._session_transcript_tail()
        # No Rich status spinner here — the goal check runs on the turn
        # worker thread, where a Live fights the input line. The bottom
        # toolbar shows "evaluating goal" while this runs.
        met, reason = evaluate_goal(self._client, goal, transcript)
        goal.turns_evaluated += 1
        goal.last_reason = reason
        if met:
            goal.achieved = True
            self.console.print(
                f"[bold green]◎ goal achieved[/] after "
                f"{goal.turns_evaluated} turn(s), {goal.elapsed_s():.0f}s — "
                f"{reason}"
            )
            clear_goal()
            return None
        if goal.turns_evaluated >= goal.max_iterations:
            self.console.print(
                f"[yellow]◎ goal stopped[/] — hit the "
                f"{goal.max_iterations}-turn cap without meeting the "
                f"condition. Last eval: {reason}"
            )
            clear_goal()
            return None
        self.console.print(
            f"[dim]◎ goal not met "
            f"({goal.turns_evaluated}/{goal.max_iterations}) — {reason}[/]"
        )
        # The evaluator's reason becomes the next turn's directive.
        return reason

    # ── Deep Think ──────────────────────────────────────────────────

    def run_deep_think(self) -> None:
        """Enter Deep Think mode: swap to the coder model, work the
        queued skill-development tasks one at a time, swap back to the
        realtime model when the queue drains or the user hits Ctrl-C.

        See docs/deep_think_design.md. The model swap means only one
        model is RAM-resident at a time. Ctrl-C is the wake interrupt:
        the in-progress task is flipped back to ``pending`` so it
        resumes next time, and the realtime model is reloaded."""
        from jaeger_os.main import run_command, switch_model
        from jaeger_os.core.background.deep_think import queue_for_layout
        from jaeger_os.core.instance.instance import InstanceLayout
        from jaeger_os.core.models.model_resolver import (
            DEFAULT_CODER_MODEL,
            DEFAULT_MODEL,
        )
        from jaeger_os.agent.prompts.reflection import reflect_on_task, save_reflection

        # The pipeline must be booted (config/lock/layout) before we can
        # swap models — _ensure_agent does that on first use.
        if self._ensure_agent() is None:
            self.console.print("[yellow]Agent not initialized.[/]")
            return

        layout = InstanceLayout(root=self.instance_dir)
        queue = queue_for_layout(layout)
        if queue.next_pending() is None:
            self.console.print("[dim]Deep Think queue is empty.[/]")
            return

        # ── swap in the coder model ──
        self.console.print(
            "[bold yellow]◎ entering Deep Think[/] — swapping to the "
            "coder model. The robot won't be conversational until it "
            "swaps back. [dim](Ctrl-C interrupts.)[/]"
        )
        self._client = None  # drop ref so the old model frees before reload
        try:
            # Plain print, not a Rich status spinner — Deep Think runs on
            # the turn worker thread, and a Live there fights the
            # main-thread input line.
            self.console.print("[yellow]◎ loading coder model…[/]")
            self._client = switch_model(DEFAULT_CODER_MODEL)
        except Exception as exc:  # noqa: BLE001
            self.console.print(
                f"[red]Couldn't load coder model ({DEFAULT_CODER_MODEL}):[/] "
                f"{exc}\n[dim]Staying on the realtime model.[/]"
            )
            # Make sure we're back on a working realtime client.
            try:
                self._client = switch_model(DEFAULT_MODEL)
            except Exception:
                pass
            return

        completed = 0
        failed = 0
        try:
            while True:
                task = queue.next_pending()
                if task is None:
                    break
                queue.mark_in_progress(task.id)
                self.console.print(
                    f"[cyan]◎ deep think ›[/] {task.description}"
                )
                outcome = "done"
                try:
                    # Framework-injected message — the canonical text
                    # lives in core/prompts/synthetic.py alongside the
                    # other auto-prompts (idle board pickup, cron),
                    # so the full set of "things the framework sends
                    # as the user" is one read.
                    from jaeger_os.agent.prompts import deep_think_directive
                    directive = deep_think_directive(task.description)
                    run_command(self._client, directive,
                                session_key=f"deepthink_{task.id}")
                    queue.mark_done(task.id, "completed in Deep Think")
                    completed += 1
                    self.console.print(f"[green]  ✓ done[/] [{task.id}]")
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001
                    outcome = f"failed: {exc}"
                    queue.mark_failed(task.id, str(exc))
                    failed += 1
                    self.console.print(f"[red]  ✗ failed[/] [{task.id}]: {exc}")
                # After-action reflection — extract a durable lesson and
                # persist it (chronological log + episodic memory).
                # Best-effort; a reflection failure never breaks the loop.
                try:
                    reflection = reflect_on_task(
                        self._client, task.description, outcome,
                    )
                    if reflection:
                        save_reflection(layout, task.description,
                                        outcome, reflection)
                        self.console.print(
                            f"[dim]  ↳ reflected: {reflection[:100]}[/]"
                        )
                except Exception:  # noqa: BLE001
                    pass
        except KeyboardInterrupt:
            n = queue.reset_in_progress()
            self.console.print(
                f"\n[yellow]◎ Deep Think interrupted[/] — "
                f"{n} task(s) flipped back to pending for next time."
            )
        finally:
            # ── swap the realtime model back in ──
            self.console.print(
                "[bold yellow]◎ leaving Deep Think[/] — reloading the "
                "realtime model…"
            )
            self._client = None
            try:
                self.console.print("[yellow]◎ loading realtime model…[/]")
                # switch_model rebuilds the agent, which re-runs the
                # skill loader — so anything Deep Think authored is now
                # live for the realtime model.
                self._client = switch_model(DEFAULT_MODEL)
            except Exception as exc:  # noqa: BLE001
                self.console.print(
                    f"[red]Failed to reload realtime model:[/] {exc}"
                )

        self.console.print(
            f"[green]◎ Deep Think complete[/] — {completed} done, "
            f"{failed} failed. New skills (if any) are now available."
        )

    # ── Auto-idle ───────────────────────────────────────────────────

    def _auto_idle_seconds(self) -> int:
        """Idle window (in seconds) before the TUI auto-enters Deep
        Think, from the instance config's ``deep_think.auto_idle_minutes``.
        0 (default) ⇒ auto-idle off. Reads the live pipeline config so
        it reflects the booted instance."""
        try:
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            if cfg is None:
                return 0
            return int(cfg.deep_think.auto_idle_minutes) * 60
        except Exception:  # noqa: BLE001
            return 0

    def _status_fragments(self) -> list[tuple[str, str]]:
        """Status-bar segments as prompt_toolkit ``(style, text)`` fragments.

        Layout mirrors Hermes's ``_get_status_bar_fragments``:

          ``✦ model │ 27.8K/262K │ [█░░░░░░░░░] 11% │ 1h 4m 12s │ ⏲ 23s``

        Each segment carries its own color — model in the Jaeger accent,
        token ratio + times in dim, the bar+percent in Hermes's
        good/warn/bad/critical colour band keyed on context usage.
        """
        running = self._turn_running.is_set()
        SEP: tuple[str, str] = ("fg:ansibrightblack", "  │  ")
        frags: list[tuple[str, str]] = []

        if running:
            frame = _SPINNER_FRAMES[int(time.time() * 8) % len(_SPINNER_FRAMES)]
            # Spinner text resolution:
            #   1. Specific ``_current_activity`` (anything other than
            #      the default "ruminating"). Set explicitly by the
            #      deep-think entry, goal-eval entry, and by tests.
            #   2. Live ``agent_status`` snapshot — surfaces the
            #      active tool, finalize step, background process, etc.
            #      as published by the agent-loop callbacks.
            #   3. Whatever ``_current_activity`` is (e.g. "ruminating"
            #      while a turn is mid-flight but the agent hasn't yet
            #      dispatched a tool), else literal "ruminating".
            from jaeger_os.main import get_agent_status, status_label
            _snap = get_agent_status()
            _cur = self._current_activity or ""
            if _cur and _cur != "ruminating":
                live = _cur
            elif _snap.get("state") not in (None, "", "ready"):
                live = status_label(_snap)
            else:
                live = _cur or "ruminating"
            frags.append((f"fg:{ACCENT_PTK}", f"{frame} {live}"))
            frags.append(SEP)

        frags.append((f"fg:{ACCENT_PTK} bold", f"✦ {self.model_name}"))
        frags.append(SEP)

        # Context-usage gauge — NOT turn progress. We label it ``ctx``
        # explicitly because users (and at least one AI auditor) read
        # the unlabelled ``10/32.8K [░░░░░░░░░░] 0%`` shape as
        # "the agent has generated 10/32.8K tokens; turn is 0% done."
        # In reality the count is system_prompt + tool_schemas +
        # history + (when the turn completes) the assistant's reply.
        # It only changes at the END of a turn. Mid-turn this bar
        # stays static even while the model is generating — which
        # made stalls look indistinguishable from active work.
        mx = max(1, self._current_ctx_max())
        pct = min(100, int(self._context_tokens / mx * 100))
        fill = pct // 10
        bar = "█" * fill + "░" * (10 - fill)
        frags.append(("fg:ansibrightblack",
                      f"ctx {_kfmt(self._context_tokens)}/{_kfmt(mx)}"))
        frags.append(SEP)
        frags.append((_pct_color(pct), f"[{bar}] {pct}% ctx"))
        frags.append(SEP)

        frags.append(("fg:ansibrightblack",
                      _format_elapsed(time.perf_counter() - self._started_at)))
        frags.append(SEP)

        if running:
            frags.append(("fg:ansibrightblack", _format_elapsed(
                time.perf_counter() - self._turn_started_at,
                live=True, with_emoji=True,
            )))
        elif self._last_turn_s > 0:
            frags.append(("fg:ansibrightblack",
                          _format_elapsed(self._last_turn_s, with_emoji=True)))
        else:
            frags.append(("fg:ansibrightblack", "⏲ 0s"))

        if self._voice is not None and self._voice.running:
            frags.append(SEP)
            frags.append(("fg:ansibrightblack", "🎙 on"))
        return frags

    def _status_line(self) -> str:
        """Plain-text status line — visible characters only, no styles.
        Single source of truth is :meth:`_status_fragments`."""
        return "".join(text for _style, text in self._status_fragments())

    def _prompt_message(self) -> Any:
        """The prompt_toolkit prompt — the pinned status bar drawn a few
        lines above the ``❯`` input line, so the input is always the
        very last line on screen (hermes layout).

        Returned as a fragment list and re-evaluated every
        ``refresh_interval``, so the bar's spinner + timer animate. This
        callable runs inside prompt_toolkit's event loop, so it is also
        where that loop is captured for :meth:`_run_on_terminal`."""
        try:
            self._ptk_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        frags: list[tuple[str, str]] = []
        if self._statusbar_on:
            import shutil
            width = max(20, shutil.get_terminal_size((80, 24)).columns)
            rule = "─" * width
            frags.append((f"fg:{ACCENT_PTK}", rule + "\n"))
            frags.append(("", "  "))
            frags.extend(self._status_fragments())
            frags.append(("", "\n"))
            frags.append((f"fg:{ACCENT_PTK}", rule + "\n"))
        frags.append((f"fg:{ACCENT_PTK} bold", "❯ "))
        return frags

    def _prompt_placeholder(self) -> Any:
        """Ghost hint shown in the empty input line — what Enter does
        mid-turn and the key shortcuts, hermes-style. Disappears the
        moment the user types."""
        return [(
            "fg:ansibrightblack",
            f"  msg → {self._busy_mode}   ·   /steer   ·   /busy   "
            "·   ^C interrupt",
        )]

    def _read_line(self) -> Any:
        """Read one line via the prompt_toolkit session — slash
        autocomplete, ghost-text, the pinned status bar, history.
        Returns the string, :data:`CTRL_C` on Ctrl-C, ``None`` on EOF."""
        if self._ptk_session is None:
            self._ptk_session = build_session()
        return read_prompt(self._ptk_session,
                           message=self._prompt_message,
                           placeholder=self._prompt_placeholder)

    # ── Turn worker (concurrent input) ──────────────────────────────

    def _run_on_terminal(self, func: Any) -> Any:
        """Run ``func()`` with exclusive terminal access — used by the
        turn worker thread when a tool needs to ask the user something.

        While a turn runs, the main thread sits in prompt_toolkit's
        ``prompt()`` and owns stdin. ``run_in_terminal`` (scheduled onto
        prompt_toolkit's loop) suspends the input line, runs ``func`` in
        a clean cooked-mode terminal, then restores the prompt. Falls
        back to a direct call when no prompt is running (piped stdin)."""
        loop = self._ptk_loop
        app = getattr(self._ptk_session, "app", None)
        if loop is None or app is None or not getattr(app, "is_running", False):
            return func()
        try:
            from prompt_toolkit.application import run_in_terminal

            # run_in_terminal must be *invoked* inside the prompt_toolkit
            # event loop (it calls get_app()); wrap it in a coroutine so
            # run_coroutine_threadsafe schedules the whole thing there.
            async def _runner() -> Any:
                return await run_in_terminal(func)

            fut = asyncio.run_coroutine_threadsafe(_runner(), loop)
            return fut.result()
        except Exception:  # noqa: BLE001
            return func()

    def _turn_worker(self) -> None:
        """Background turn-runner. Drains the turn queue and runs each
        turn (or a Deep Think pass) serially, so the main thread's input
        line never blocks. Lives for the whole REPL."""
        while not self._worker_stop.is_set():
            try:
                item = self._turn_queue.get(timeout=0.25)
            except queue.Empty:
                self._idle_tick()
                continue
            if item is _WORKER_SHUTDOWN:
                break
            source, text = item
            self._turn_running.set()
            self._turn_started_at = time.perf_counter()
            self._current_activity = "ruminating"
            nxt: str | None = None
            try:
                if source == _DEEPTHINK_SOURCE:
                    self.run_deep_think()
                else:
                    self.run_turn(text, source=source)
                    # Goal loop — evaluate after every real turn; a
                    # not-met goal re-enqueues itself as the next turn.
                    self._current_activity = "evaluating goal"
                    try:
                        from jaeger_os.main import set_agent_status
                        set_agent_status("thinking", detail="evaluating goal")
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        nxt = self._post_turn_goal_check()
                    except Exception:  # noqa: BLE001
                        nxt = None
            except Exception as exc:  # noqa: BLE001
                self.console.print(f"[red]turn failed:[/] {exc}")
            finally:
                self._turn_running.clear()
                self._current_activity = ""
            if nxt:
                self._turn_queue.put(("goal", nxt))

    def _idle_tick(self) -> None:
        """Called by the worker whenever the turn queue is empty —
        once the idle window has elapsed, look for autonomous work:
        first the Deep Think queue, then the kanban board. Quietly
        keeps waiting when neither has anything actionable."""
        if self._turn_running.is_set() or self._idle_fired:
            return
        idle = self._auto_idle_seconds()
        if idle <= 0 or time.monotonic() - self._last_activity < idle:
            return
        if not self._turn_queue.empty():
            return
        self._idle_fired = True
        # Order matters: Deep Think is the heavier, more deliberate
        # mode (long-form skill authoring). The board is the lighter
        # "knock out a TODO" mode. Try DT first since a pending DT
        # job was probably authored explicitly; fall through to the
        # board when DT is empty.
        if self._maybe_auto_deep_think():
            return
        self._maybe_auto_work_board()

    def _maybe_auto_deep_think(self) -> bool:
        """Try to enter Deep Think for an approved queued task. Returns
        True when DT was started (so the caller skips the board path).
        Quietly returns False when nothing approved is pending."""
        try:
            from jaeger_os.core.background.deep_think import queue_for_layout
            from jaeger_os.core.instance.instance import InstanceLayout
            queue_ = queue_for_layout(InstanceLayout(root=self.instance_dir))
            if queue_.next_pending() is None:
                return False  # nothing approved to work
        except Exception:  # noqa: BLE001
            return False
        self._turn_running.set()
        self._turn_started_at = time.perf_counter()
        self._current_activity = "deep think"
        try:
            from jaeger_os.main import set_agent_status
            set_agent_status("deep_think", detail="thinking")
        except Exception:  # noqa: BLE001 — status indicator must never crash a turn
            pass
        try:
            self.console.print(
                "[dim]◎ idle — entering Deep Think to work the queue.[/]"
            )
            self.run_deep_think()
        finally:
            self._turn_running.clear()
            self._current_activity = ""
        return True

    def _maybe_auto_work_board(self) -> bool:
        """Fall-through idle path: if the kanban board has actionable
        cards (backlog / ready / in_progress), submit a synthetic
        'work the board' prompt to the regular turn queue. Returns
        True when a turn was submitted. The synthetic prompt string
        lives in ``core/prompts/synthetic.py`` — one place to find
        every framework-injected message."""
        try:
            from jaeger_os.core.background.board import has_actionable_work
            from jaeger_os.core.instance.instance import InstanceLayout
            from jaeger_os.agent.prompts import AUTO_BOARD_PROMPT
            layout = InstanceLayout(root=self.instance_dir)
            if not has_actionable_work(layout):
                return False
        except Exception:  # noqa: BLE001 — board access must never crash idle
            return False
        self.console.print(
            "[dim]◎ idle — picking up a kanban card.[/]"
        )
        # Goes through the standard turn queue so it shares the
        # llm_lock, status pipeline, and TUI rendering with a normal
        # user turn — no parallel codepath to maintain.
        self._turn_queue.put(("kanban_idle", AUTO_BOARD_PROMPT))
        return True

    def _resolve_pending_confirm(self, line: str) -> bool:
        """Route a typed line to a tier-gated tool waiting for approval.

        When a turn's tool is blocked in
        :meth:`_TuiConfirmationProvider.confirm`, the user's next
        non-slash line IS the y/n/a answer — hand it over and wake the
        worker thread. Returns True when a confirmation was pending (and
        the line was consumed), False otherwise."""
        box = self._pending_confirm
        if box is None:
            return False
        box["answer"] = line
        box["event"].set()
        return True

    def _submit_turn(self, source: str, text: str) -> None:
        """Hand a turn to the worker. If a turn is already running, route
        by the busy-input mode (hermes ``/busy``): interrupt the running
        turn, queue after it, or steer it."""
        self._last_activity = time.monotonic()
        self._idle_fired = False
        if source == "voice" and self._turn_running.is_set():
            self._coalesce_pending_voice_turn(text)
            return
        if not self._turn_running.is_set():
            self._turn_queue.put((source, text))
            return
        mode = self._busy_mode
        if mode == "queue":
            self.console.print(
                "[dim]＋ queued — runs after the current turn.[/]")
            self._turn_queue.put((source, text))
        elif mode == "steer":
            self._submit_steer(text)
        else:  # interrupt (default)
            from jaeger_os.main import request_turn_cancel
            request_turn_cancel()
            self.console.print(
                "[dim]⨯ interrupting — your new message is up next.[/]")
            self._turn_queue.put((source, text))

    def _coalesce_pending_voice_turn(self, text: str) -> None:
        """Merge voice phrases heard during a busy turn into one next turn.

        Voice is a live stream, unlike typed input. If the model is busy
        and the mic commits five phrases, replaying those as five stale
        turns makes the assistant lag behind reality. Keep at most one
        pending voice turn and append newer phrases to it.
        """
        phrase = (text or "").strip()
        if not phrase:
            return
        with self._voice_queue_lock:
            with self._turn_queue.not_empty:
                merged: list[str] = []
                kept = []
                while self._turn_queue.queue:
                    item = self._turn_queue.queue.popleft()
                    if (
                        isinstance(item, tuple)
                        and len(item) == 2
                        and item[0] == "voice"
                    ):
                        merged.extend(_split_coalesced_voice(item[1]))
                    else:
                        kept.append(item)
                merged.append(phrase)
                for item in kept:
                    self._turn_queue.queue.append(item)
                self._turn_queue.queue.append((
                    "voice", _format_coalesced_voice(merged),
                ))
                self._turn_queue.not_empty.notify()
        self._log_voice(
            "[dim]🎙 coalesced — will handle latest voice batch next.[/]",
            kind="info",
        )

    def _submit_steer(self, text: str) -> None:
        """Steer the running turn — stop it at the next tool-call
        boundary and continue with this guidance.

        The cancel is checked between agent-loop nodes, so the in-flight
        tool call finishes first (the steer "arrives after the next tool
        call", as in hermes). The partial turn's messages are kept in
        session history, so the steered turn continues with full context
        — the agent absorbs the new direction without losing momentum."""
        from jaeger_os.main import request_turn_cancel
        request_turn_cancel()
        self.console.print(
            "[dim]⤳ steering — finishing the current step, then taking "
            "your guidance.[/]")
        self._turn_queue.put(("text", text))

    def _drain_turn_queue(self) -> None:
        """Discard every queued (not-yet-started) turn — used when the
        user Ctrl-C's to abandon everything pending."""
        try:
            while True:
                self._turn_queue.get_nowait()
        except queue.Empty:
            pass

    def _voice_poll_loop(self) -> None:
        """Background mic poller — runs only while voice is live. Each
        committed phrase becomes a turn, routed through the same
        busy-input rules as a typed line."""
        while not self._voice_stop.is_set():
            v = self._voice
            if v is None or not v.running:
                break
            try:
                phrase = v.poll(timeout=0.25)
            except Exception:  # noqa: BLE001
                phrase = None
            if not phrase:
                continue
            from jaeger_os.core.voice import is_non_speech_marker
            if is_non_speech_marker(phrase):
                self._log_voice(
                    f"[dim][skipped — non-speech: {phrase!r}][/]",
                    kind="skipped",
                )
                continue
            if is_exit_phrase(phrase):
                self.console.print(
                    "[dim]🎙  mic off (spoken stop). /voice on to resume.[/]")
                self._voice_stop.set()
                v.stop()
                self._voice = None
                break
            v.chime("wake")
            self._submit_turn("voice", phrase)

    # ── Busy-input mode ─────────────────────────────────────────────

    def _configured_busy_mode(self) -> str:
        """The busy-input mode from config (``display.busy_input_mode``).
        Defaults to 'interrupt'."""
        try:
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            mode = str(getattr(getattr(cfg, "display", None),
                               "busy_input_mode", "interrupt")).lower()
            return mode if mode in ("interrupt", "queue", "steer") \
                else "interrupt"
        except Exception:  # noqa: BLE001
            return "interrupt"

    def set_busy_mode(self, mode: str) -> bool:
        """Set + persist the busy-input mode. Returns False if unknown."""
        mode = (mode or "").strip().lower()
        if mode not in ("interrupt", "queue", "steer"):
            return False
        self._busy_mode = mode
        try:
            from jaeger_os.core.instance.instance import InstanceLayout
            from jaeger_os.core.instance.schemas import dump_yaml
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            if cfg is not None:
                cfg.display.busy_input_mode = mode
                dump_yaml(
                    InstanceLayout(root=self.instance_dir).config_path, cfg)
        except Exception:  # noqa: BLE001
            pass
        return True

    # ── Slash dispatch ──────────────────────────────────────────────

    def _dispatch_slash(self, line: str) -> bool:
        """Run a slash command on the main thread. Returns True to quit
        the REPL. Commands that swap the model / instance / pipeline are
        refused while a turn is running."""
        words = line.strip().lstrip("/").split()
        name = words[0].lower() if words else ""
        if name in _TURN_UNSAFE_SLASH and self._turn_running.is_set():
            self.console.print(
                f"[yellow]⏳ a turn is running[/] — Ctrl-C to stop it, or "
                f"wait, before [bold]/{name}[/]."
            )
            return False
        result = dispatch(line, self.slash_ctx)
        if result.message:
            self.console.print(result.message)
        if result.quit:
            return True
        # /deepthink start → run Deep Think on the worker so the input
        # line stays live while it drains the queue.
        if result.extras.get("deep_think_start"):
            self._turn_queue.put((_DEEPTHINK_SOURCE, ""))
        # /goal <condition> fires the first goal turn immediately.
        if result.extras.get("goal_just_set"):
            from jaeger_os.main import get_goal
            active = get_goal()
            if active is not None:
                self._submit_turn("goal", active.condition)
        return False

    # ── REPL ────────────────────────────────────────────────────────

    def repl(self) -> int:
        """Main loop. Returns the exit code.

        The agent turn runs on a background worker thread, so the input
        line is always live — you can type a follow-up, a slash command,
        or (per ``display.busy_input_mode``) interrupt / queue / steer
        while the agent is still working. This is the hermes
        concurrent-input model.

        A goal, when active, drives the next turn from the worker's
        post-turn evaluation. ``deep_think.auto_idle_minutes`` makes the
        worker auto-enter Deep Think after an idle window."""
        self.render_boot()
        # Boot eagerly so the Jaeger is operational the instant the
        # prompt appears.
        self._boot_eager()
        self._print_ready_hint()
        self._busy_mode = self._configured_busy_mode()
        if not sys.stdin.isatty():
            # Piped / non-interactive stdin: no live user to type
            # alongside the agent — run turns synchronously.
            return self._repl_synchronous()
        self._worker = threading.Thread(
            target=self._turn_worker, name="jaeger-turn", daemon=True)
        self._worker.start()
        try:
            while True:
                raw = self._read_line()
                if raw is None:                       # Ctrl-D / EOF
                    self.console.print("\n[dim]bye.[/]")
                    break
                if raw is CTRL_C:                     # Ctrl-C
                    if self._pending_confirm is not None:
                        # A permission prompt is waiting — Ctrl-C denies
                        # it and lets the turn unwind.
                        self._resolve_pending_confirm("")
                        self.console.print("[dim]⨯ permission denied.[/]")
                        continue
                    if (self._turn_running.is_set()
                            or not self._turn_queue.empty()):
                        from jaeger_os.main import request_turn_cancel
                        request_turn_cancel()
                        self._drain_turn_queue()
                        self.console.print(
                            "[dim]⨯ interrupted — turn(s) stopped.[/]")
                    else:
                        self.console.print(
                            "[dim](Ctrl-C — nothing running. Ctrl-D or "
                            "/quit to exit.)[/]")
                    continue
                line = str(raw).strip()
                if not line:
                    continue
                if is_slash(line):
                    if self._dispatch_slash(line):
                        break
                    continue
                # A non-slash line while a tier-gated tool waits for
                # approval IS the y/n/a answer — route it to the
                # confirmation, do not start a new turn.
                if self._resolve_pending_confirm(line):
                    continue
                if _wants_voice_mode(line):
                    # "turn the mic on" typed as text → bring it up.
                    self.start_voice()
                    continue
                self._submit_turn("text", line)
        finally:
            self._shutdown()
        return 0

    def _repl_synchronous(self) -> int:
        """Fallback REPL for piped / non-interactive stdin — read a
        line, run the turn inline, repeat. No worker thread: there is no
        live user typing alongside the agent."""
        pending_goal: str | None = None
        try:
            while True:
                source = "text"
                if pending_goal is not None:
                    line, source, pending_goal = pending_goal, "goal", None
                else:
                    try:
                        raw = input()
                    except (EOFError, KeyboardInterrupt):
                        break
                    line = str(raw).strip()
                    if not line:
                        continue
                    if is_slash(line):
                        result = dispatch(line, self.slash_ctx)
                        if result.message:
                            self.console.print(result.message)
                        if result.quit:
                            break
                        continue
                self.run_turn(line, source=source)
                pending_goal = self._post_turn_goal_check()
        finally:
            self._shutdown()
        return 0

    def _shutdown(self) -> None:
        """Tear down the turn worker, the mic, and the pipeline on REPL
        exit. Idempotent enough to run from the REPL's finally block.

        0.2.6: previously this left llama-cpp's Metal backend, Kokoro's
        audio stream, and Whisper's Metal backend to be finalised by
        Python's interpreter-shutdown GC. Three native libraries' GC
        finalisers were racing each other AND PortAudio's CoreAudio
        callback threads — Obj-C runtime sometimes hit a freed handle
        from the wrong thread and the process exited with
        ``zsh: segmentation fault``.

        New order: explicit ordered teardown HERE, in this frame, while
        we still hold the GIL and the audio callback threads are still
        alive. Drop our references and force a ``gc.collect()`` so
        finalisers fire deterministically; THEN let the audio threads
        wind down.
        """
        # Cancel any in-flight turn so the worker unwinds promptly.
        try:
            from jaeger_os.main import request_turn_cancel
            request_turn_cancel()
        except Exception:  # noqa: BLE001
            pass
        self._worker_stop.set()
        self._turn_queue.put(_WORKER_SHUTDOWN)
        if self._worker is not None:
            self._worker.join(timeout=10.0)
            self._worker = None
        # Mic capture threads come down before the pipeline they feed.
        self.stop_voice()
        # Release the instance lock + shut down extensions before
        # dropping the llama-cpp client (its destructor needs the GIL
        # but not the lock).
        if self._boot is not None:
            try:
                self._boot.cleanup()
            except Exception:  # noqa: BLE001
                pass
        self._agent = None
        self._client = None
        self._boot = None

        # 0.3.0-refactor step 1: explicitly close the Kokoro persistent
        # sounddevice OutputStream BEFORE the per-call ``sd.stop()`` /
        # ``gc.collect()`` dance below.  We own this stream; closing it
        # deterministically here keeps PortAudio's CoreAudio callback
        # thread from touching a freed Python object during interpreter
        # shutdown — the residual cause of the 0.2.6 ``Pa_Terminate``
        # segfault.
        try:
            from jaeger_os.main import _pipeline
            tts_node = _pipeline.get("tts_node")
            if tts_node is not None and hasattr(tts_node, "shutdown"):
                tts_node.shutdown()
        except Exception:  # noqa: BLE001 — best-effort
            pass

        # Stop any stragglers (per-call sd.play streams used by
        # play_async's barge-in path; these aren't routed through our
        # persistent player).
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:  # noqa: BLE001 — best-effort
            pass

        # Drop the global pipeline references (set by ``init_extensions``)
        # so the next collect() can finalise llama-cpp + Whisper here,
        # not during interpreter shutdown.
        try:
            from jaeger_os.main import _pipeline
            for key in (
                "client", "agent", "thinking_runner",
                "tts_node", "stt_node", "whisper", "voice_pipeline",
            ):
                _pipeline.pop(key, None)
        except Exception:  # noqa: BLE001
            pass

        # Force a deterministic finalisation pass. Two collect() rounds
        # because freeing one wrapper can release the last reference to
        # another (Kokoro pipeline → audio stream → sounddevice handle).
        try:
            import gc
            gc.collect()
            gc.collect()
        except Exception:  # noqa: BLE001
            pass

        # Brief grace so PortAudio's CoreAudio callback thread finishes
        # its current frame before we let the Python interpreter start
        # tearing down its own state.
        try:
            import time
            time.sleep(0.05)
        except Exception:  # noqa: BLE001
            pass


# ── Entry point ─────────────────────────────────────────────────────


def run(
    *,
    skip_model: bool = False,
    instance_name: str | None = None,
) -> int:
    """Public entry: construct + run the Jaeger TUI. Returns exit
    code. ``skip_model=True`` is for banner-only mode.

    0.2.6: ``instance_name`` plumbs the ``--instance NAME`` CLI flag
    through to ``JaegerTUI(instance_dir=…)``. Before, ``run()`` took
    no instance arg, so the TUI silently fell back to the (deleted)
    ``jaeger_os/instance/default/`` bundled path and the auto-wizard
    fired against ``default`` regardless of what ``--instance`` said.

    Enforces TUI singleton via :mod:`.singleton`: if another TUI for
    this instance is already running, surface a friendly message and
    exit non-zero."""
    from jaeger_os.core.instance.instance import (
        default_instance_name, resolve_instance_dir,
    )
    name = instance_name or default_instance_name()
    instance_dir = Path(resolve_instance_dir(name))
    if not skip_model:
        try:
            from .singleton import acquire_tui_slot, existing_tui_pid
            run_dir = instance_dir / "run"
            existing = existing_tui_pid(run_dir)
            if existing is not None:
                print(
                    f"Jaeger TUI already running (pid={existing}) for "
                    f"instance {name!r}. Close it first, or use the "
                    f"tray's Open TUI to bring it to the front.",
                    file=sys.stderr,
                )
                return 1
            acquire_tui_slot(run_dir)
        except Exception:  # noqa: BLE001 — slot mgmt must never block boot
            pass
    return JaegerTUI(
        skip_model=skip_model,
        instance_dir=instance_dir,
    ).repl()


if __name__ == "__main__":
    sys.exit(run())
