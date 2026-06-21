"""computer_use — the framework's flagship skill.

Covers the pure grounding logic (accessibility-tree parsing, click-point
maths, AppleScript escaping, key-chord resolution) and that the skill
registers its seven tools. The action tools are NOT invoked — on a Mac
they would really drive the screen — so only validation / pure paths
are exercised here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = (
    # dev/tests/jaeger_os/skills/ → repo root is 4 up.
    Path(__file__).resolve().parents[4]
    / "jaeger_os" / "agent" / "skills"
    / "computer_use_v1" / "computer_use.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("computer_use", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cu = _load()


# ── pure grounding logic ─────────────────────────────────────────────


def test_applescript_escape():
    assert cu._esc('say "hi"\\') == 'say \\"hi\\"\\\\'


def test_parse_screen_centre_point():
    parsed = cu._parse_screen(
        "app: Safari\nwindow: Start\n"
        "AXButton ||| Reload ||| reload ||| 10 ||| 20 ||| 100 ||| 40\n"
    )
    assert parsed["app"] == "Safari" and parsed["count"] == 1
    el = parsed["elements"][0]
    assert el["role"] == "AXButton"
    assert el["x"] == 60 and el["y"] == 40  # centre of (10,20)+(100,40)


def test_parse_screen_empty_field_and_missing_geometry():
    parsed = cu._parse_screen(
        "app: X\nwindow: Y\n"
        "AXTextField ||| Search |||  ||| 5 ||| 5 ||| 50 ||| 24\n"
        "AXGroup ||| g ||| ||| ? ||| ? ||| 0 ||| 0\n"
    )
    assert parsed["count"] == 2
    assert parsed["elements"][0]["description"] == ""   # empty field survives
    assert "x" not in parsed["elements"][1]             # no geometry → no x/y


def test_build_press_script_chord():
    script, err = cu._build_press_script("cmd+c")
    assert err is None
    assert "command down" in script and 'keystroke "c"' in script


def test_build_press_script_named_key():
    script, err = cu._build_press_script("return")
    assert err is None and "key code 36" in script


def test_build_press_script_rejects_unknown():
    script, err = cu._build_press_script("nonsense")
    assert script is None and err is not None


# ── input validation (no OS interaction) ─────────────────────────────


def test_open_app_rejects_empty():
    assert cu.open_app("")["ok"] is False


def test_click_rejects_non_integer():
    assert cu.click("nope", 0)["ok"] is False


def test_menu_select_requires_both_args():
    assert cu.menu_select("File", "")["ok"] is False


# ── registration ─────────────────────────────────────────────────────


class _StubAgent:
    """Records what register() wires up, without a real pydantic-ai agent."""

    def __init__(self) -> None:
        self.tools: list[str] = []

    def tool_plain(self, fn):
        self.tools.append(fn.__name__)
        return fn


def test_register_wires_seven_tools():
    agent = _StubAgent()
    cu.register(agent)
    assert sorted(agent.tools) == sorted([
        "computer_screenshot", "computer_read_screen", "computer_open_app",
        "computer_click", "computer_type_text", "computer_press_key",
        "computer_menu_select",
    ])
