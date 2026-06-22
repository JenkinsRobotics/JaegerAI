"""``jaeger rich-tui`` — daemon-attached Rich client.

This is a **NEW** surface, not a replacement. The 0.1.0 ``jaeger tui``
in ``../tui/`` keeps booting the model in-process and stays untouched
(see ``feedback-preserve-0.1.0-surfaces`` in the project memory).

Where the existing ``tui/`` runs the agent in the same process as
the UI, ``rich_tui/`` connects to a daemon that's already running
(``jaeger start``) and drives it over the Unix-domain socket — same
``chat.send`` / ``chat.subscribe`` verbs ``jaeger attach`` uses, with
Rich/prompt-toolkit chrome on top instead of plain prints.

If no daemon is running, ``jaeger rich-tui`` prints a clear message
and exits non-zero — it does NOT fall back to in-process boot. Use
``jaeger tui`` for the standalone path.
"""

from __future__ import annotations
