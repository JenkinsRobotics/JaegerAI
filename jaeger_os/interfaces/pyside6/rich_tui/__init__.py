"""rich_tui — the PySide6 windowed chat surface.

Holds :mod:`window`, the Rich-TUI-styled chat window the chassis boots as
the windowed app's main surface (``jaeger.windowed.toml`` →
``rich_tui.window:make_surface``). It renders the agent's session-tagged
event stream (ChatReply / AgentState / ToolEvent / AgentRequest) over the
in-process bus — no separate process, no daemon.

(The original daemon-attached REPL that lived here — ``app.py`` /
``__main__.py`` — was removed with the daemon; the in-process windowed
window replaced it.)
"""

from __future__ import annotations
