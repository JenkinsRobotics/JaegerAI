"""Heuristic goal parser — string → list[Action].

The parser turns natural-language goals into the action-dict list
the planner already knows how to dispatch. It deliberately stays
small and pattern-based; an unrecognised goal returns a single
``"goal"`` action so the planner surfaces "no engine claimed
this" rather than silently dispatching to vision.

This file pins:
  * each documented pattern resolves to the right (kind, target,
    args) shape
  * chains ("X and Y") decompose into multiple actions
  * unrecognised text returns ``[Action(kind="goal", ...)]``
  * empty / whitespace input returns ``[]`` (caller treats as no-op)
"""

from __future__ import annotations

import pytest

from jaeger_ai.agent.skills.macos_computer_v1.goal_parser import parse_goal


# ── opens ──────────────────────────────────────────────────────────


def test_open_app():
    actions = parse_goal("open Calculator")
    assert len(actions) == 1
    assert actions[0].kind == "open"
    assert actions[0].target == "Calculator"


def test_launch_and_start_are_synonyms_for_open():
    for verb in ("launch", "start", "run"):
        actions = parse_goal(f"{verb} Notes")
        assert actions[0].kind == "open"
        assert actions[0].target == "Notes"


def test_open_url_routes_to_open_url_kind():
    """A URL in an ``open ...`` clause must route to ``open_url``
    so the browser engine picks it up, not the AppleScript open
    that would just launch a browser app."""
    actions = parse_goal("open https://example.com")
    assert len(actions) == 1
    assert actions[0].kind == "open_url"
    assert actions[0].target == "https://example.com"


# ── clicks / presses ───────────────────────────────────────────────


def test_click_label():
    actions = parse_goal("click Save")
    assert actions[0].kind == "press"
    assert actions[0].args == {"label": "Save"}
    assert actions[0].target == ""


def test_click_label_in_app():
    actions = parse_goal("click 5 in Calculator")
    assert actions[0].kind == "press"
    assert actions[0].args == {"label": "5"}
    assert actions[0].target == "Calculator"


def test_press_named_key_routes_to_press_key():
    """Keys like ``Return`` / ``Tab`` go to press_key, not press
    (which is an AX button label match)."""
    actions = parse_goal("press Return")
    assert actions[0].kind == "press_key"
    assert actions[0].args == {"key": "Return"}


def test_press_unknown_label_routes_to_press():
    actions = parse_goal("press Send")
    assert actions[0].kind == "press"
    assert actions[0].args == {"label": "Send"}


# ── types ──────────────────────────────────────────────────────────


def test_type_value():
    actions = parse_goal('type hello world')
    assert actions[0].kind == "type"
    assert actions[0].args == {"value": "hello world"}


def test_type_value_in_target():
    actions = parse_goal('type Pickup groceries in Reminders')
    assert actions[0].kind == "type"
    assert actions[0].args == {"value": "Pickup groceries"}
    assert actions[0].target == "Reminders"


def test_type_value_into_target():
    actions = parse_goal('enter password into Login')
    assert actions[0].kind == "type"
    assert actions[0].args == {"value": "password"}
    assert actions[0].target == "Login"


# ── reads / queries ────────────────────────────────────────────────


def test_read_label():
    actions = parse_goal("read Result")
    assert actions[0].kind == "read_value"
    assert actions[0].args == {"label": "Result"}


def test_read_label_in_target():
    actions = parse_goal("read the Result in Calculator")
    assert actions[0].kind == "read_value"
    assert actions[0].args == {"label": "Result"}
    assert actions[0].target == "Calculator"


def test_what_is_query_routes_to_focused_window():
    actions = parse_goal("what's in Calculator?")
    assert actions[0].kind == "focused_window"
    assert actions[0].target == "Calculator"


# ── menus ──────────────────────────────────────────────────────────


def test_menu_path():
    actions = parse_goal("menu File > New")
    assert actions[0].kind == "menu_select"
    assert actions[0].args == {"path": "File > New"}


def test_menu_three_deep():
    actions = parse_goal("select View > Zoom > Zoom In")
    assert actions[0].kind == "menu_select"
    assert actions[0].args == {"path": "View > Zoom > Zoom In"}


# ── chains ─────────────────────────────────────────────────────────


def test_chain_with_and():
    actions = parse_goal("open Calculator and click 5")
    assert len(actions) == 2
    assert actions[0].kind == "open"
    assert actions[0].target == "Calculator"
    assert actions[1].kind == "press"
    assert actions[1].args == {"label": "5"}


def test_chain_with_then():
    actions = parse_goal("open Notes then type Buy milk")
    assert len(actions) == 2
    assert actions[0].target == "Notes"
    assert actions[1].kind == "type"


def test_chain_three_steps():
    actions = parse_goal("open Calculator and click 5 and click +")
    assert len(actions) == 3
    assert [a.kind for a in actions] == ["open", "press", "press"]


# ── context carry — the "open X" sticky-target rule ────────────


def test_chain_carries_app_target_after_open():
    """After ``open Calculator``, subsequent ``click X`` / ``type
    X`` in the chain inherit ``target=Calculator``. Without this,
    the planner can't route the click to Calculator's AX tree."""
    actions = parse_goal("open Calculator and click 5 and click +")
    assert actions[0].kind == "open" and actions[0].target == "Calculator"
    assert actions[1].kind == "press"
    assert actions[1].target == "Calculator"   # ← inherited
    assert actions[1].args == {"label": "5"}
    assert actions[2].kind == "press"
    assert actions[2].target == "Calculator"   # ← inherited
    assert actions[2].args == {"label": "+"}


def test_explicit_target_in_chain_overrides_sticky():
    """A clause that names its own target (``click X in Y``)
    wins over the sticky context. The next clause goes back to
    the original sticky."""
    actions = parse_goal(
        "open Calculator and click Save in Notes and click 5"
    )
    assert actions[0].target == "Calculator"
    # Explicit "in Notes" → that target wins for this clause.
    assert actions[1].target == "Notes"
    # Next clause inherits the original sticky (Calculator), not
    # the explicit one (Notes) — the explicit was scoped to its
    # clause.
    assert actions[2].target == "Calculator"


def test_second_open_re_anchors_the_chain():
    """``open Calculator and X and open Notes and Y`` should
    route X to Calculator and Y to Notes."""
    actions = parse_goal(
        "open Calculator and click 5 and open Notes and type hello"
    )
    assert actions[0].target == "Calculator"
    assert actions[1].target == "Calculator"    # inherited
    assert actions[2].target == "Notes"          # re-anchored by 2nd open
    assert actions[3].target == "Notes"          # inherited from new anchor


# ── fallback / edge cases ─────────────────────────────────────────


def test_empty_returns_no_actions():
    assert parse_goal("") == []
    assert parse_goal("   ") == []


def test_unrecognised_goes_to_goal_kind():
    """An unrecognised string returns a single ``goal`` action so
    the planner surfaces "no engine claimed this" — the agent
    learns to decompose explicitly."""
    actions = parse_goal("dance the macarena")
    assert len(actions) == 1
    assert actions[0].kind == "goal"
    assert "dance the macarena" in actions[0].args["text"]
