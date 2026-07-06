"""rich_tui — the windowed chat surface (Pattern 1's main window).

A thin PySide6 view over the chassis bus: it publishes ``ChatMessage`` and
renders ``ChatReply`` / ``AgentState`` — it never imports the agent (the
GUI/logic-separation rule), so swapping PySide6 for Swift moves no logic.

This is the **windowed twin of the Rich terminal TUI**
(``jaeger_os.interfaces.tui``): the same banner, the same ``#3aa0ff``
accent, the same ``❯`` prompt and turn rules — a transcript, not an
iMessage bubble sheet.  The terminal renders to a console; this renders
the same shape to a QTextEdit.  Tool-execution / reasoning lines land
when the bridge starts emitting per-tool events on the bus.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
)
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from jaeger_os.app.surfaces import make_bus_bridge
from jaeger_os.core.messages import ChatMessage
from jaeger_os.interfaces.tui.banner import JAEGER_ASCII, TAGLINE
from jaeger_os.interfaces.tui.theme import ACCENT  # #3aa0ff — the brand accent

# Terminal palette — the windowed echo of the Rich TUI's console.
_CANVAS = "#0B0E14"
_PANEL = "#131720"
_INK = "#DDE2EA"
_INK_DIM = "#888F9C"
_RULE = "#21344a"
_MONO = ("SF Mono", "Menlo", "Consolas", "monospace")

# Slash commands — single source of truth for the completer, /help, and
# the dispatcher. Client-side UI actions (the CLI TUI has more; these are
# the windowed surface's).
_SLASH_COMMANDS = {
    "/new": "new conversation",
    "/clear": "clear the screen",
    "/copy": "copy the last reply",
    "/sessions": "list recent conversations",
    "/plugins": "list / activate messaging plugins",
    "/mode": "show / switch mode (normal · high · deep-sleep)",
    "/help": "list commands",
}


class ChatWindow(QWidget):
    """Bus-backed chat window in the Rich-TUI aesthetic. Publishes
    ``ChatMessage`` on send; renders ``ChatReply`` / ``AgentState`` as a
    monospace transcript + a status line. Closing hides it (the menu-bar
    tray is the always-on surface)."""

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self.ctx = ctx
        # Display name tracks the ACTIVE character (what the agent is playing),
        # so the title / banner / reply prefix match the persona — not the
        # boot-time core identity. Recomputed each time the window opens.
        try:
            from jaeger_os.interfaces.avatar_player.window import agent_name
            self._agent_name = agent_name(ctx)
        except Exception:  # noqa: BLE001
            self._agent_name = (
                getattr(getattr(ctx, "core", None), "agent_name", None)
                or getattr(ctx, "agent_name", None) or "agent")
        self._messages: list[tuple[str, str]] = []   # (role, text) view-model
        # This window's conversation. One app-agent, many windows/chats —
        # the session scopes history + routes replies to this window. A
        # short uuid keeps it unique without a counter.
        self._session = uuid.uuid4().hex[:8]
        self._turn_start = 0.0
        # Live activity stream (thoughts + tool use) shown during a turn.
        self._activity_trace = self._read_activity_trace()  # full|summary|clear|off
        self._progress_anchor: int | None = None
        self._progress_steps = 0
        self._mode = "normal"   # runtime mode, updated by /sense/mode
        self._turn_timer = QTimer(self)
        self._turn_timer.setInterval(1000)
        self._turn_timer.timeout.connect(self._tick_status)

        self.setObjectName("JrosChatWindow")
        self.setWindowTitle(f"JROS — {self._agent_name} · {self._mode}")
        self.resize(760, 660)
        self._build_ui()
        self._emit_banner()

        # The one sanctioned bus→Qt hop (signal emission crosses threads).
        self._bridge = make_bus_bridge(
            ctx.bus,
            ["/sense/chat", "/sense/agent_state", "/sense/tool", "/sense/request",
             "/sense/activity", "/sense/mode"])
        self._bridge.message.connect(self._on_msg)

    # ── UI ────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QWidget#JrosChatWindow {{ background-color: {_CANVAS}; }}
            QLabel#HeaderLabel {{
                font-family: {_MONO[0]}, {_MONO[1]}, monospace;
                font-size: 12px;
                color: {_INK_DIM};
                padding: 8px 16px;
                background: {_PANEL};
                border-bottom: 1px solid {_RULE};
            }}
            QTextEdit#Transcript {{
                background-color: {_CANVAS};
                border: none;
                padding: 6px 14px;
            }}
            QLabel#StatusLabel {{
                font-family: {_MONO[0]}, {_MONO[1]}, monospace;
                color: {_INK_DIM};
                padding: 4px 16px;
                font-size: 11px;
                background: {_PANEL};
                border-top: 1px solid {_RULE};
            }}
            QLabel#Prompt {{
                color: {ACCENT};
                font-family: {_MONO[0]}, {_MONO[1]}, monospace;
                font-size: 16px;
                font-weight: bold;
                padding-left: 6px;
            }}
            QLineEdit#Composer {{
                background: {_PANEL};
                border: 1px solid {_RULE};
                border-radius: 8px;
                padding: 9px 12px;
                font-family: {_MONO[0]}, {_MONO[1]}, monospace;
                font-size: 13px;
                color: {_INK};
            }}
            QLineEdit#Composer:focus {{ border: 1px solid {ACCENT}; }}
            QPushButton#SendBtn {{
                background-color: {ACCENT};
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                padding: 8px 16px;
            }}
            QPushButton#SendBtn:hover {{ background-color: #57b0ff; }}
            QPushButton#SendBtn:disabled {{ background-color: #2a4a6a; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QLabel(f"jros · {self._agent_name} · local")
        self.header.setObjectName("HeaderLabel")
        root.addWidget(self.header)

        self.transcript = QTextEdit()
        self.transcript.setObjectName("Transcript")
        self.transcript.setReadOnly(True)
        self.transcript.setFrameShape(QFrame.Shape.NoFrame)
        self.transcript.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        base = QFont(_MONO[0], 13)
        base.setStyleHint(QFont.StyleHint.Monospace)
        self.transcript.setFont(base)
        root.addWidget(self.transcript, stretch=1)

        self.status = QLabel("")
        self.status.setObjectName("StatusLabel")
        root.addWidget(self.status)

        composer = QHBoxLayout()
        composer.setContentsMargins(12, 8, 12, 12)
        composer.setSpacing(8)

        prompt = QLabel("❯")
        prompt.setObjectName("Prompt")
        composer.addWidget(prompt)

        self.input = QLineEdit()
        self.input.setObjectName("Composer")
        self.input.setPlaceholderText(
            f"Message {self._agent_name}…   (/help for commands)")
        self.input.returnPressed.connect(self._send)
        # Slash autocompletion — typing "/" pops the available commands,
        # like the CLI TUI's completer. Only matches slash inputs (normal
        # messages don't start with "/", so the popup stays hidden).
        completer = QCompleter(list(_SLASH_COMMANDS), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.popup().setStyleSheet(
            f"background:{_PANEL}; color:{_INK}; border:1px solid {_RULE};"
            f"font-family:{_MONO[0]}, {_MONO[1]}, monospace; font-size:13px;"
            f"selection-background-color:{ACCENT};")
        self.input.setCompleter(completer)
        composer.addWidget(self.input, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("SendBtn")
        self.send_btn.clicked.connect(self._send)
        composer.addWidget(self.send_btn)
        root.addLayout(composer)

    # ── transcript rendering ──────────────────────────────────────
    def _emit(self, text: str, color: str, *, bold: bool = False,
              italic: bool = False) -> None:
        """Append a run of coloured monospace text at the transcript end."""
        cur = self.transcript.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontFamilies(list(_MONO))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        fmt.setFontItalic(italic)
        cur.insertText(text, fmt)
        self.transcript.setTextCursor(cur)

    def _emit_banner(self) -> None:
        self._emit(JAEGER_ASCII.strip("\n") + "\n", ACCENT, bold=True)
        self._emit(TAGLINE + "\n\n", _INK_DIM)

    def _emit_rule(self) -> None:
        self._emit("─" * 64 + "\n", _RULE)

    def _insert_markdown(self, text: str) -> None:
        """Render the agent's reply as Markdown (bold / lists / code /
        headings) via Qt's built-in parser, forced to the ink colour so
        it's visible on the dark canvas. Fixes the literal-asterisk leak."""
        doc = QTextDocument()
        doc.setDefaultFont(QFont(_MONO[0], 13))
        doc.setMarkdown(
            text, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
        sel = QTextCursor(doc)
        sel.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(_INK))
        sel.mergeCharFormat(fmt)   # keeps bold/italic, just recolours
        cur = self.transcript.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertFragment(QTextDocumentFragment(doc))
        self.transcript.setTextCursor(cur)

    # ── input → bus ───────────────────────────────────────────────
    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        if text.startswith("/"):
            self._handle_slash(text)
            return
        self._submit(text)

    def submit_external(self, text: str) -> None:
        """Inject a message from another surface (e.g. the tray Pill): render
        the user line + publish, exactly as if typed here."""
        text = (text or "").strip()
        if text:
            self._submit(text)

    def _submit(self, text: str) -> None:
        self._append_turn("user", text)
        self._set_busy(True)
        self.ctx.bus.publish(
            ChatMessage(text=text, source="gui", session=self._session))

    # ── slash commands (client-side UI actions) ───────────────────
    def _handle_slash(self, cmd: str) -> None:
        name = cmd[1:].split()[0].lower() if len(cmd) > 1 else ""
        if name in ("help", "?", ""):
            self._emit_system("   ".join(
                f"{c} — {d}" for c, d in _SLASH_COMMANDS.items()))
        elif name == "new":
            self._new_conversation()
        elif name == "clear":
            self.transcript.clear()
            self._emit_banner()
        elif name == "copy":
            self._copy_last_reply()
        elif name == "sessions":
            self._list_sessions()
        elif name == "plugins":
            self._handle_plugins(cmd[1:].split()[1:])
        elif name == "mode":
            self._handle_mode(cmd[1:].split()[1:])
        else:
            self._emit_system(f"unknown command: /{name} — try /help")

    def _handle_mode(self, args: list[str]) -> None:
        """`/mode` shows the current mode + options; `/mode high` switches. The
        model swap is slow (~60-90s) so it runs OFF the UI thread; the new mode
        comes back over /sense/mode and updates the title."""
        from jaeger_os.core.runtime import modes
        if not args:
            self._emit_system(
                f"mode: {self._mode}  ·  options: {', '.join(modes.list_modes())}"
                f"  ·  /mode <name> to switch")
            return
        target = args[0].strip().lower()
        if target not in modes.list_modes():
            self._emit_system(f"unknown mode {target!r} — options: {', '.join(modes.list_modes())}")
            return
        if target == self._mode:
            self._emit_system(f"already in {target} mode")
            return
        self._emit_system(f"switching to {target} mode… (model swap ~60-90s — it's not stuck)")
        threading.Thread(target=lambda: modes.set_mode(target),
                         daemon=True, name="mode-switch").start()

    def _on_mode(self, msg: Any) -> None:
        self._mode = getattr(msg, "mode", "") or self._mode
        self.setWindowTitle(f"JROS — {self._agent_name} · {self._mode}")
        self._emit_system(f"◆ mode: {self._mode}")

    def _handle_plugins(self, args: list[str]) -> None:
        """`/plugins` → live bridges + per-plugin status; `/plugins activate
        <name>` → bring one live in-process from its saved credential (same
        path as the agent's activate_plugin tool + the Studio button)."""
        try:
            from jaeger_os.agent.tools.plugins import list_plugins
            from jaeger_os.main import activate_plugin_inprocess
            from jaeger_os.plugins import list_bridges
        except Exception as exc:  # noqa: BLE001
            self._emit_system(f"plugins unavailable: {exc}")
            return
        if args and args[0].lower() == "activate" and len(args) > 1:
            res = activate_plugin_inprocess(args[1].strip().lower())
            if res.get("started"):
                tail = " (already running)" if res.get("already_running") else ""
                self._emit_system(f"✓ {res.get('channel')} bridge is live{tail}")
            else:
                self._emit_system(f"✗ {res.get('error')}")
            return
        live = list_bridges()
        lines = [f"live bridges: {', '.join(live) if live else 'none'}"]
        for p in (list_plugins().get("plugins") or []):
            lines.append(f"  • {p.get('name')}: {p.get('status')}")
        lines.append("→ /plugins activate <name> to bring one live")
        self._emit_system("\n".join(lines))

    def _new_conversation(self) -> None:
        """Fresh conversation against the same app-agent — new session id
        (history scope) + a cleared screen. Windows/chats come and go; the
        agent persists."""
        self._session = uuid.uuid4().hex[:8]
        self._messages.clear()
        self.transcript.clear()
        self._emit_banner()
        self._emit_system("new conversation")
        self.input.setFocus()

    def _copy_last_reply(self) -> None:
        from PySide6.QtWidgets import QApplication
        last = next((t for role, t in reversed(self._messages)
                     if role == "assistant"), None)
        if last:
            QApplication.clipboard().setText(last)
            self._emit_system("copied last reply")
        else:
            self._emit_system("nothing to copy yet")

    def _list_sessions(self) -> None:
        """Recent persisted conversations (the durable session store)."""
        try:
            from jaeger_os.core.sessions import get_store
            store = get_store()
            rows = store.list_sessions(limit=15) if store is not None else None
        except Exception as exc:  # noqa: BLE001
            self._emit_system(f"sessions unavailable: {exc}")
            return
        if rows is None:
            self._emit_system("no session store (no instance bound)")
            return
        if not rows:
            self._emit_system("no past conversations yet")
            return
        self._emit_system(f"recent conversations ({len(rows)}):")
        for r in rows:
            label = (r.get("title") or r.get("preview") or "(untitled)")[:56]
            mark = "● " if r["id"] == self._session else "  "
            self._emit(f"  {mark}{r['id']}  {label}  ·  {r['messages']} msgs\n",
                       _INK_DIM)
        QTimer.singleShot(20, self._scroll_to_bottom)

    def _emit_system(self, text: str) -> None:
        self._emit(f"\n  {text}\n", _INK_DIM, italic=True)
        QTimer.singleShot(20, self._scroll_to_bottom)

    # ── bus → transcript ──────────────────────────────────────────
    def _on_msg(self, msg: Any) -> None:
        # Route by session: one app-agent fans events to every window;
        # render only this conversation's (and untagged/global) messages.
        session = getattr(msg, "session", "")
        if session and session != self._session:
            return
        if msg.topic == "/sense/chat":
            self._collapse_progress()   # apply activity_trace before the reply
            if msg.text:
                self._append_turn("assistant", msg.text)
            self._set_busy(False)
        elif msg.topic == "/sense/tool":
            self._emit_tool(msg)
        elif msg.topic == "/sense/activity":
            self._emit_activity(msg)
        elif msg.topic == "/sense/mode":
            self._on_mode(msg)
        elif msg.topic == "/sense/request":
            self._on_request(msg)
        elif msg.topic == "/sense/agent_state":
            if msg.state == "thinking":
                self._set_busy(True)
            elif msg.state == "error":
                self._set_busy(False)
                self.status.setText("⚠ error")
            else:  # idle — annotate the resting status with the ctx gauge.
                # The chat reply (published just before idle) already ran
                # _set_busy(False) → "✓ replied in Xs"; only stop the timer
                # here if that didn't happen, then append "· ctx 42%".
                if self._turn_timer.isActive():
                    self._set_busy(False)
                detail = getattr(msg, "detail", "") or ""
                if detail:
                    cur = self.status.text()
                    self.status.setText(f"{cur}  ·  {detail}" if cur else detail)

    def _on_request(self, msg: Any) -> None:
        """A mid-turn agent prompt (approval/clarify/secret). Show it, answer
        over the bus — the turn is blocked on the agent worker thread until
        an AgentResponse with this id arrives."""
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        from jaeger_os.core.messages import AgentResponse
        kind = getattr(msg, "kind", "approval")
        options = list(getattr(msg, "options", ()) or [])
        prompt = getattr(msg, "prompt", "") or "The agent is asking for input."

        if kind == "secret" or (kind == "clarify" and not options):
            text, ok = QInputDialog.getText(self, "Agent request", prompt)
            answer = text if ok else ""
        else:  # approval / clarify with choices → buttons
            box = QMessageBox(self)
            box.setWindowTitle("Agent request")
            box.setText(prompt)
            buttons = {}
            for opt in (options or ["allow", "deny"]):
                b = box.addButton(opt.capitalize(),
                                  QMessageBox.ButtonRole.AcceptRole)
                buttons[b] = opt
            box.exec()
            answer = buttons.get(box.clickedButton(), "deny")

        self.ctx.bus.publish(AgentResponse(
            id=getattr(msg, "id", ""), answer=answer, session=self._session))
        self._emit_system(f"{prompt}  → {answer}")

    def _emit_tool(self, msg: Any) -> None:
        """Live tool activity — the windowed echo of the TUI's ``┊`` lines.
        ``start`` updates the status bar; ``done``/``error`` drop a line."""
        name = getattr(msg, "name", "") or "tool"
        phase = getattr(msg, "phase", "start")
        if phase == "start":
            self.status.setText(f"⏵ running {name}…")
            return
        if phase == "error":
            self._emit(f"  ⏵ {name}", ACCENT, bold=True)
            self._emit("  ✗\n", "#FF6B6B")
        else:  # done
            elapsed = getattr(msg, "elapsed_s", 0.0) or 0.0
            self._emit(f"  ⏵ {name}", ACCENT, bold=True)
            self._emit(f"  ·  {elapsed:.1f}s\n", _INK_DIM)
        # back to the live thinking readout
        if self._turn_start:
            self._tick_status()
        QTimer.singleShot(20, self._scroll_to_bottom)

    # ── live activity stream ──────────────────────────────────────
    def _read_activity_trace(self) -> str:
        try:
            from jaeger_os.core.instance.instance import (
                InstanceLayout, default_instance_name, resolve_instance_dir)
            from jaeger_os.core.instance.schemas import Config, load_yaml
            lay = InstanceLayout(root=resolve_instance_dir(default_instance_name()))
            val = (load_yaml(lay.config_path, Config).display.activity_trace
                   or "full").lower()
            return val if val in ("full", "summary", "clear", "off") else "full"
        except Exception:  # noqa: BLE001 — default to the full trace
            return "full"

    def _doc_end(self) -> int:
        from PySide6.QtGui import QTextCursor
        c = self.transcript.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        return c.position()

    def _emit_activity(self, msg: Any) -> None:
        """One live progress line (a thought or a tool action) during a turn —
        dimmed + italic, distinct from the reply. Off when activity_trace=off."""
        if self._activity_trace == "off":
            return
        text = (getattr(msg, "text", "") or "").strip()
        if not text:
            return
        if self._progress_anchor is None:
            self._progress_anchor = self._doc_end()
            self._progress_steps = 0
        self._progress_steps += 1
        glyph = "▸" if getattr(msg, "kind", "") == "tool" else "·"
        self._emit(f"  {glyph} {text}\n", _INK_DIM, italic=True)
        QTimer.singleShot(20, self._scroll_to_bottom)

    def _collapse_progress(self) -> None:
        """Apply activity_trace to this turn's progress block as the reply
        lands: full/off keep it; clear removes it; summary collapses it to one
        dimmed line."""
        anchor, steps = self._progress_anchor, self._progress_steps
        self._progress_anchor = None
        self._progress_steps = 0
        if anchor is None or self._activity_trace in ("full", "off"):
            return
        from PySide6.QtGui import QTextCursor
        cur = self.transcript.textCursor()
        cur.setPosition(anchor)
        cur.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        if self._activity_trace == "summary" and steps:
            dur = (self._fmt_dur(time.monotonic() - self._turn_start)
                   if self._turn_start else "")
            self._emit(f"  ▸ {steps} steps{('  ·  ' + dur) if dur else ''}\n",
                       _INK_DIM, italic=True)

    # ── helpers ───────────────────────────────────────────────────
    def _append_turn(self, role: str, text: str) -> None:
        self._messages.append((role, text))
        if role == "user":
            # ● prompt line under a rule — the operator's turn, like the
            # terminal TUI's rule-framed user message.
            self._emit("\n", _INK)
            self._emit_rule()
            self._emit("● ", ACCENT, bold=True)
            self._emit(text + "\n", _INK)
        else:
            # ✦ agent label, then the reply rendered as Markdown.
            self._emit("\n✦ ", ACCENT, bold=True)
            self._emit(f"{self._agent_name}\n", ACCENT, bold=True)
            self._insert_markdown(text)
            self._emit("\n", _INK)
        QTimer.singleShot(20, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_busy(self, busy: bool) -> None:
        # The input stays live while the agent thinks — follow-ups and
        # slash commands work mid-turn. The bridge queues turns (one model,
        # one at a time), so a follow-up runs after the current reply.
        if busy:
            if not self._turn_timer.isActive():
                self._turn_start = time.monotonic()
                self._turn_timer.start()
                # Mark where this turn's progress block begins (for clear/summary).
                if self._activity_trace != "off":
                    self._progress_anchor = self._doc_end()
                    self._progress_steps = 0
            self._tick_status()
        else:
            self._turn_timer.stop()
            if self._turn_start:
                self.status.setText(
                    f"✓ replied in {self._fmt_dur(time.monotonic() - self._turn_start)}")
                self._turn_start = 0.0
            else:
                self.status.setText("")
        self.input.setFocus()

    def _tick_status(self) -> None:
        """Live turn timer — the CLI TUI's elapsed-seconds readout."""
        if self._turn_start:
            self.status.setText(
                f"● thinking…  {self._fmt_dur(time.monotonic() - self._turn_start)}")

    @staticmethod
    def _fmt_dur(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"

    def rendered_text(self) -> str:
        """All message bodies joined — a stable surface for tests/inspection
        (the transcript is the view; this is the view-model)."""
        return "\n".join(t for _role, t in self._messages)

    # ── tray-persist: the X hides instead of quitting ─────────────
    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        event.ignore()
        self.hide()

    def teardown(self) -> None:
        try:
            self._bridge.close()
        except Exception:  # noqa: BLE001
            pass


def make_surface(ctx: Any, spec: Any = None) -> ChatWindow:  # noqa: ARG001
    return ChatWindow(ctx)
