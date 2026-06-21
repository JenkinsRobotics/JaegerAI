"""Interactive picker — the centered arrow-key selection box.

The picker drives ``/model`` and ``/busy`` (no-arg). It cannot be
exercised interactively here, but it must degrade gracefully: an empty
option list and a non-TTY environment both return ``None`` rather than
raising, so a slash handler can always fall back to "unchanged".
"""

from __future__ import annotations

from jaeger_os.interfaces.tui.picker import pick


def test_pick_empty_options_returns_none() -> None:
    assert pick("title", []) is None


def test_pick_without_a_tty_returns_none() -> None:
    # pytest runs with no controlling terminal — radiolist_dialog().run()
    # raises, and pick() must swallow that and return None.
    result = pick("Select", [("a", "Option A"), ("b", "Option B")])
    assert result is None
