"""prompt_toolkit input layer for the TUI.

A ``PromptSession`` gives the input line everything Rich's ``Prompt``
could not:

  - a slash-command autocomplete dropdown (see :mod:`.completion`)
  - dimmed inline ghost-text suggestions
  - command history (↑ / ↓)
  - reverse-i-search, kill-ring, the usual readline editing

The status bar is rendered as part of the prompt **message** — a few
lines above the ``❯`` input line — so the input is always the very
last line on screen (hermes layout). ``read_prompt`` returns the typed
string, :data:`CTRL_C` on Ctrl-C, or ``None`` on EOF (Ctrl-D). Rich
owns the scrollback (banner, panels, agent output) which scrolls above
the pinned prompt via ``patch_stdout``.
"""

from __future__ import annotations

from typing import Any, Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout

from .completion import SlashAutoSuggest, SlashCompleter


# Returned by read_prompt when the user pressed Ctrl-C. Distinct from
# ``None`` (EOF / Ctrl-D) so the REPL can interrupt the running turn on
# Ctrl-C but only quit on Ctrl-D.
CTRL_C = object()

# The prompt re-renders on this interval even when the user is not
# typing — so the status bar's spinner + timer animate while a turn
# runs on the worker thread.
_REFRESH_INTERVAL = 0.3


def build_session() -> PromptSession:
    """A PromptSession with slash autocomplete, ghost-text suggestions,
    and in-memory history. Built once and reused so history persists
    across turns within a session.

    ``erase_when_done`` clears the whole prompt (status bar + input
    line) on submit so the typed text isn't echoed twice — the REPL
    re-renders it as the hermes-style ``──── / ● message`` turn header
    (see ``app._render_turn_header``)."""
    return PromptSession(
        completer=SlashCompleter(),
        auto_suggest=SlashAutoSuggest(),
        complete_while_typing=True,
        complete_in_thread=True,
        history=InMemoryHistory(),
        multiline=False,
        erase_when_done=True,
    )


def read_prompt(
    session: PromptSession,
    *,
    message: Callable[[], Any],
    placeholder: Callable[[], Any] | None = None,
) -> Any:
    """Read one line of input. Returns the typed string, :data:`CTRL_C`
    on Ctrl-C, or ``None`` on EOF (Ctrl-D).

    ``message`` is a callable returning prompt_toolkit formatted text —
    the pinned status bar plus the ``❯`` line. It is re-evaluated every
    ``refresh_interval`` so the bar animates. ``patch_stdout`` keeps a
    concurrent ``print`` from the turn worker thread (tool activity, the
    answer box) from corrupting the live prompt — that output scrolls
    cleanly above it.

    ``raw=True`` is essential: the turn worker prints **Rich** output
    (panels, rules, colour), which is ANSI escape sequences. The default
    ``patch_stdout`` proxy processes text and mangles those escapes —
    they show up as literal ``?[33m`` garbage. ``raw=True`` passes the
    bytes straight through so the colour renders."""
    try:
        with patch_stdout(raw=True):
            return session.prompt(
                message,
                refresh_interval=_REFRESH_INTERVAL,
                placeholder=placeholder,
            )
    except KeyboardInterrupt:
        return CTRL_C
    except EOFError:
        return None
