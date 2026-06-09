"""Smoke test for computer_use.

Runs as a subprocess from the skill loader before registration. It loads
the module standalone and checks it is healthy — it does NOT run any
AppleScript (no clicking the user's screen, no permission needs), so it
passes on any host. The action tools self-check the platform at call
time.
"""

import importlib.util
import sys
from pathlib import Path


def main() -> int:
    spec = importlib.util.spec_from_file_location(
        "computer_use",
        Path(__file__).resolve().parent.parent / "computer_use.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # All seven tool functions + register() are present.
    for fn in ("screenshot", "read_screen", "open_app", "click",
               "type_text", "press_key", "menu_select", "register"):
        assert callable(getattr(mod, fn, None)), f"missing {fn}"

    # Pure helper — AppleScript string escaping.
    assert mod._esc('a"b\\c') == 'a\\"b\\\\c', mod._esc('a"b\\c')

    # Pure helper — parse a read_screen dump into structured elements
    # with a centre-point click target.
    parsed = mod._parse_screen(
        "app: Safari\nwindow: Start Page\n"
        "AXButton ||| Reload ||| reload this page ||| 10 ||| 20 ||| 100 ||| 40\n"
    )
    assert parsed["app"] == "Safari", parsed
    assert parsed["window"] == "Start Page", parsed
    assert parsed["count"] == 1, parsed
    el = parsed["elements"][0]
    assert el["role"] == "AXButton" and el["name"] == "Reload", el
    assert el["x"] == 60 and el["y"] == 40, el  # centre of (10,20)+(100,40)

    print("computer_use smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
