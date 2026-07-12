"""Slash-command autocomplete for the TUI.

A prompt_toolkit ``Completer`` + ``AutoSuggest`` built from the slash-
command registry. Typing ``/`` pops a filtered dropdown of matching
commands (with their one-line summaries); the dimmed inline "ghost
text" predicts the rest of the command as you type. Mirrors hermes's
``SlashCommandCompleter`` / ``SlashCommandAutoSuggest``.

Pure data — no model, no agent state — so it is unit-testable and the
TUI just wires it onto the input widget.
"""

from __future__ import annotations

from typing import Iterable

from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.completion import Completer, Completion

from .slash_commands import REGISTRY


# Known subcommands per command — completed after the command name +
# a space. Commands whose argument is free-form (an instance name, a
# model name, a goal condition) are deliberately absent.
SUBCOMMANDS: dict[str, tuple[str, ...]] = {
    "voice": ("on", "off", "wake", "followup", "bargein"),
    "goal": ("clear",),
    "deepthink": ("add", "list", "approve", "start", "stop"),
    "board": ("show", "add", "approve", "done", "move"),
    "model": ("use",),
}


def _command_names() -> list[tuple[str, str]]:
    """(name, summary) for every registered slash command, sorted."""
    return sorted((c.name, c.summary) for c in REGISTRY)


class SlashCompleter(Completer):
    """Completes ``/command`` names and their known subcommands."""

    def get_completions(self, document, complete_event) -> Iterable[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        body = text[1:]

        # Phase 1 — still typing the command name (no space yet).
        if " " not in body:
            prefix = body.lower()
            for name, summary in _command_names():
                if name.startswith(prefix):
                    yield Completion(
                        name,
                        start_position=-len(prefix),
                        display=f"/{name}",
                        display_meta=summary,
                    )
            return

        # Phase 2 — command is typed; complete a known subcommand.
        name, _, sub = body.partition(" ")
        subs = SUBCOMMANDS.get(name.lower())
        if not subs:
            return
        sub_prefix = sub.lower()
        for s in subs:
            if s.startswith(sub_prefix):
                yield Completion(s, start_position=-len(sub_prefix), display=s)


class SlashAutoSuggest(AutoSuggest):
    """Dim inline 'ghost text' — predicts the rest of a slash command
    from the first unique-prefix match. Returns None for ordinary text."""

    def get_suggestion(self, buffer, document) -> Suggestion | None:
        text = document.text
        if not text.startswith("/") or " " in text:
            return None
        prefix = text[1:].lower()
        if not prefix:
            return None
        for name, _summary in _command_names():
            if name.startswith(prefix) and name != prefix:
                return Suggestion(name[len(prefix):])
        return None
