"""Skill loader smoke — verifies the macos_computer module imports.

Doesn't actually fire AX / AppleScript at runtime (those need real
permissions on a real Mac); just confirms the engine modules load,
the planner can wire them, and the tool registration call doesn't
raise. The real engines are exercised in
``tests/jaeger_os/skills/test_macos_computer_*.py``.
"""

from __future__ import annotations

# Self-bootstrap: when the skill loader invokes this file as a
# subprocess (`python smoke_test.py`), CWD is the skill folder and
# the repo root may not be on ``sys.path``.  Walk four parents up
# (tests/ → macos_computer_v1/ → skills/ → jaeger_os/ → repo root)
# and prepend it so the ``from jaeger_os.agent.skills...`` imports below
# resolve.
import os.path as _osp
import sys as _sys
_REPO = _osp.dirname(_osp.dirname(_osp.dirname(_osp.dirname(_osp.dirname(_osp.abspath(__file__))))))
if _REPO not in _sys.path:
    _sys.path.insert(0, _REPO)


def main() -> int:
    # Engine imports — every tier must load even when its runtime
    # backend (PyObjC for AX, Playwright for browser) isn't ready;
    # ``is_available`` returns the reason.
    from jaeger_os.agent.skills.macos_computer_v1.engines.ax_engine import AXEngine
    from jaeger_os.agent.skills.macos_computer_v1.engines.applescript_engine import AppleScriptEngine
    from jaeger_os.agent.skills.macos_computer_v1.engines.browser_engine import BrowserEngine
    from jaeger_os.agent.skills.macos_computer_v1.engines.vision_engine import VisionEngine

    for cls in (AXEngine, AppleScriptEngine, BrowserEngine, VisionEngine):
        eng = cls()
        ready, detail = eng.is_available()
        assert isinstance(ready, bool)
        assert isinstance(detail, str)

    # Planner — confidence selection must work without firing any
    # engine (pure metadata read).
    from jaeger_os.agent.skills.macos_computer_v1.engines import Action
    from jaeger_os.agent.skills.macos_computer_v1 import planner

    # An open_url action should ladder to browser_engine (priority 20)
    # over ax (30) and vision (90). AppleScript abstains.
    chosen, conf = planner.select_engine(Action(
        kind="open_url", args={}, target="https://example.com",
    ))
    # browser may be unavailable in CI (no chromium) — in that case
    # the planner falls through to vision; either is acceptable here.
    # The point is that selection itself completes.
    assert chosen is None or chosen.name in ("browser", "vision")

    # Calculator press should pick applescript (priority 10) over
    # everything else when osascript is present.
    chosen2, _ = planner.select_engine(Action(
        kind="press", args={"value": "5"}, target="Calculator",
    ))
    # On non-Mac (no osascript) all four abstain or return errors;
    # don't pin a specific result, just confirm completion.
    assert chosen2 is None or chosen2.name in ("applescript", "ax", "vision")

    return 0


if __name__ == "__main__":  # pragma: no cover — skill loader entry
    import sys
    sys.exit(main())
