"""Benchmark for computer_use — scored evaluation of the pure logic.

The act tools need a live desktop + permissions, which can't be scored
deterministically. What CAN be scored is the grounding/parsing logic the
reliability of the skill rests on: accessibility-tree parsing, centre-
point maths, AppleScript escaping, and key-chord resolution. This
benchmark exercises exactly those.

Prints one JSON object: {score, passed, total, cases, notes}.
"""

import importlib.util
import json
import sys
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "computer_use",
        Path(__file__).resolve().parent.parent / "computer_use.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = _load()
    cases = []

    # 1 — read_screen parsing: app/window + element count
    parsed = mod._parse_screen(
        "app: Notes\nwindow: All\n"
        "AXButton ||| New ||| new note ||| 5 ||| 5 ||| 50 ||| 30\n"
        "AXTextField ||| Search ||| ||| 100 ||| 8 ||| 200 ||| 24\n"
    )
    cases.append({"name": "parse_app_window",
                  "ok": parsed["app"] == "Notes" and parsed["window"] == "All"})
    cases.append({"name": "parse_count", "ok": parsed["count"] == 2})

    # 2 — centre-point maths: (5,5)+(50,30) → centre (30,20)
    el0 = parsed["elements"][0]
    cases.append({"name": "centre_point",
                  "ok": el0.get("x") == 30 and el0.get("y") == 20,
                  "got": (el0.get("x"), el0.get("y"))})

    # 3 — an element with no geometry parses but carries no x/y
    no_geo = mod._parse_screen(
        "app: X\nwindow: Y\nAXGroup ||| g ||| ||| ? ||| ? ||| 0 ||| 0\n"
    )
    cases.append({"name": "missing_geometry_safe",
                  "ok": no_geo["count"] == 1 and "x" not in no_geo["elements"][0]})

    # 4 — AppleScript escaping of quotes + backslashes
    cases.append({"name": "applescript_escape",
                  "ok": mod._esc('say "hi"\\') == 'say \\"hi\\"\\\\'})

    # 5 — key-chord resolution: cmd+c → keystroke with a command modifier
    script, err = mod._build_press_script("cmd+c")
    cases.append({"name": "chord_resolves",
                  "ok": err is None and script is not None
                  and "command down" in script and 'keystroke "c"' in script})

    # 6 — named special key → a key code, no modifier
    script, err = mod._build_press_script("return")
    cases.append({"name": "named_key_resolves",
                  "ok": err is None and script is not None
                  and "key code 36" in script})

    # 7 — an unknown key is rejected cleanly, not crashed on
    script, err = mod._build_press_script("nonsense_key_name")
    cases.append({"name": "unknown_key_rejected",
                  "ok": script is None and err is not None})

    passed = sum(1 for c in cases if c["ok"])
    total = len(cases)
    print(json.dumps({
        "score": round(passed / total, 4) if total else 0.0,
        "passed": passed,
        "total": total,
        "cases": cases,
        "notes": "Scores the grounding/parsing logic; live UI actions "
                 "need a desktop + Accessibility permission.",
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
