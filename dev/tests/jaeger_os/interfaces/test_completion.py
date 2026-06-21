"""Slash-command autocomplete — SlashCompleter / SlashAutoSuggest.

The dropdown + ghost-text logic the TUI wires onto its input widget.
Pure data (built from the slash-command registry), so it is testable
without a running prompt_toolkit Application.
"""

from __future__ import annotations

from prompt_toolkit.document import Document

from jaeger_os.interfaces.tui.completion import (
    SlashAutoSuggest,
    SlashCompleter,
)


def _complete(text: str) -> list[str]:
    comp = SlashCompleter()
    doc = Document(text, len(text))
    return [c.text for c in comp.get_completions(doc, None)]


# ── completion dropdown ──────────────────────────────────────────────


def test_plain_text_yields_no_completions() -> None:
    assert _complete("hello world") == []


def test_bare_slash_lists_commands() -> None:
    out = _complete("/")
    assert "help" in out and "voice" in out and "quit" in out


def test_prefix_filters_to_matching_commands() -> None:
    assert _complete("/vo") == ["voice"]   # only /voice starts with "vo"


def test_subcommand_completion() -> None:
    after_space = _complete("/voice ")
    assert {"on", "off", "wake", "bargein"} <= set(after_space)
    assert _complete("/voice w") == ["wake"]


def test_unknown_command_has_no_subcommands() -> None:
    assert _complete("/help ") == []


# ── inline ghost-text suggestion ─────────────────────────────────────


def test_autosuggest_predicts_the_rest_of_a_command() -> None:
    sug = SlashAutoSuggest()
    s = sug.get_suggestion(None, Document("/vo", 3))
    assert s is not None and s.text == "ice"        # /vo → /voice


def test_autosuggest_silent_on_full_command_and_plain_text() -> None:
    sug = SlashAutoSuggest()
    assert sug.get_suggestion(None, Document("/voice", 6)) is None
    assert sug.get_suggestion(None, Document("hello", 5)) is None
