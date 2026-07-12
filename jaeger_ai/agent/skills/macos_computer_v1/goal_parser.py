"""Heuristic goal decomposition — string → list[Action].

The planner's ``computer_do`` accepts either a list of action dicts
OR a plain-string goal. The list path is the high-fidelity one (the
model has already decided the steps). The string path goes through
this parser, which matches a small set of common patterns:

  * "open X"                       → open(X)
  * "open X and Y"                 → open(X) → parse(Y)
  * "click X"                      → press(label=X)
  * "click X in Y"                 → press(target=Y, label=X)
  * "type X"                       → type(text=X)
  * "type X in Y"                  → type(target=Y, text=X)
  * "type X into Y"                → same
  * "press X"                      → press_key(key=X) for known keys; else
                                     press(label=X)
  * "read X"                       → read_value(label=X)
  * "read X in Y"                  → read_value(target=Y, label=X)
  * "go to URL" / "open URL"       → open_url(URL)  (when URL is http(s))
  * "what's in X" / "what is X"    → read_value(label=X)
  * "menu File > New"              → menu_select(path="File > New")

Patterns NOT matched fall through to a single ``{"kind": "goal",
"args": {"text": <full string>}}`` action. The planner returns
"no engine claimed this" so the agent learns to decompose
explicitly (or for the model to be more specific).

This is INTENTIONALLY simple. A future pass can plug in a tiny
LLM-driven decomposer; for now, the patterns cover the common
verbs without dragging an extra model invocation into the loop.
"""

from __future__ import annotations

import re

from jaeger_ai.agent.skills.macos_computer_v1.engines import Action


# Recognised single-key names for ``press X``. Anything else falls
# through to "press by label" (AX press of a button labelled X).
_KEY_NAMES: frozenset[str] = frozenset({
    "return", "enter", "tab", "escape", "esc", "space", "delete",
    "backspace", "up", "down", "left", "right",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10",
    "f11", "f12",
})


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def parse_goal(goal: str) -> list[Action]:
    """Turn a natural-language goal into a list of actions. Returns
    the actions in execution order. An unrecognised goal returns a
    single ``"goal"`` action so the planner can surface "no engine
    claimed this" to the agent.

    Empty / whitespace-only goal returns an empty list — the caller
    should treat that as a no-op (and the planner does).
    """
    text = (goal or "").strip()
    if not text:
        return []
    return _parse_chain(text)


def _parse_chain(text: str) -> list[Action]:
    """A goal may be one action ("open Calculator") or a chain
    ("open Calculator and add 5+5"). Split on the obvious linkers
    and recurse so each segment matches a single pattern.

    **Context carry**: after an ``open X`` (or any action that
    pinned a target), subsequent actions in the chain inherit that
    target unless they specify their own. This is what makes
    ``"open Calculator and click 5"`` actually route the click to
    Calculator instead of system-wide. The agent shouldn't have to
    re-name the app in every clause."""
    # Split on " and " / " then " / "; " — the natural English
    # chain linkers. We keep splits tight so "Notes and Reminders"
    # (an app name) doesn't get cut in half: only split when the
    # following segment also starts with a recognised verb.
    parts: list[str] = []
    for raw in re.split(r"\s+(?:and then|then|and|;)\s+", text,
                        flags=re.IGNORECASE):
        if raw.strip():
            parts.append(raw.strip())
    if len(parts) == 1:
        return _parse_one(parts[0])

    out: list[Action] = []
    sticky_target = ""
    for segment in parts:
        step_actions = _parse_one(segment)
        for action in step_actions:
            # Propagate the sticky target into actions that didn't
            # name one explicitly. ``open`` / ``open_url`` /
            # ``menu_select`` / ``focused_window`` reset or own
            # their target; everything else inherits.
            if action.target:
                if action.kind in ("open", "open_url"):
                    # An open in the chain re-anchors the context.
                    sticky_target = action.target
                # Either way, an explicit target wins.
                out.append(action)
                continue
            if sticky_target and action.kind in (
                "press", "type", "set_value", "read_value",
                "menu_select", "focused_window", "list_windows",
                "move_window", "resize_window",
            ):
                action = Action(
                    kind=action.kind, args=action.args,
                    target=sticky_target,
                )
            out.append(action)
    return out


def _parse_one(text: str) -> list[Action]:
    """Match ONE clause against the pattern table."""
    t = text.strip()
    lower = t.lower()

    # URL shortcut — any clause containing a URL routes to open_url.
    m = _URL_RE.search(t)
    if m and lower.startswith(("open ", "go to ", "visit ", "browse ")):
        return [Action(kind="open_url", args={}, target=m.group(0))]

    # "open X" / "launch X" / "start X"
    m = re.match(r"^(?:open|launch|start|run)\s+(.+)$", t, re.IGNORECASE)
    if m:
        target = m.group(1).strip().strip(".")
        return [Action(kind="open", args={}, target=target)]

    # "click X in Y" / "press X in Y"
    m = re.match(r"^(?:click|press|tap|push)\s+(.+?)\s+(?:in|on|inside)\s+(.+)$",
                 t, re.IGNORECASE)
    if m:
        label, target = m.group(1).strip(), m.group(2).strip()
        return [Action(kind="press", args={"label": label}, target=target)]

    # "click X" / "press X" — distinguish key names from labels.
    m = re.match(r"^(?:click|press|tap|push)\s+(.+)$", t, re.IGNORECASE)
    if m:
        label = m.group(1).strip().strip(".")
        if label.lower() in _KEY_NAMES:
            return [Action(kind="press_key", args={"key": label}, target="")]
        return [Action(kind="press", args={"label": label}, target="")]

    # "type X in Y" / "type X into Y"
    m = re.match(r"^(?:type|enter|input)\s+(.+?)\s+(?:in|into|to)\s+(.+)$",
                 t, re.IGNORECASE)
    if m:
        value, target = m.group(1).strip().strip('"\''), m.group(2).strip()
        return [Action(kind="type", args={"value": value}, target=target)]

    # "type X"
    m = re.match(r"^(?:type|enter|input)\s+(.+)$", t, re.IGNORECASE)
    if m:
        value = m.group(1).strip().strip('"\'').strip(".")
        return [Action(kind="type", args={"value": value}, target="")]

    # "menu File > New" / "menu File>New" / "select File > New"
    m = re.match(r"^(?:menu|select)\s+(.+(?:\s*>\s*.+)+)$", t, re.IGNORECASE)
    if m:
        path = m.group(1).strip()
        return [Action(kind="menu_select", args={"path": path}, target="")]

    # "read X in Y" / "read the X in Y"
    m = re.match(r"^read\s+(?:the\s+)?(.+?)\s+(?:in|of|from)\s+(.+)$",
                 t, re.IGNORECASE)
    if m:
        label, target = m.group(1).strip(), m.group(2).strip()
        return [Action(kind="read_value", args={"label": label}, target=target)]

    # "read X"
    m = re.match(r"^read\s+(?:the\s+)?(.+)$", t, re.IGNORECASE)
    if m:
        label = m.group(1).strip().strip(".")
        return [Action(kind="read_value", args={"label": label}, target="")]

    # "what's in X" / "what is X showing" — verification queries.
    m = re.match(r"^what(?:'s| is)\s+(?:in|on|showing in)\s+(.+)$",
                 t, re.IGNORECASE)
    if m:
        target = m.group(1).strip().strip("?")
        return [Action(kind="focused_window", args={}, target=target)]

    # Unrecognised — return a single "goal" action so the agent
    # sees a clear "no engine claimed this" error and learns to
    # decompose explicitly.
    return [Action(kind="goal", args={"text": t}, target="")]


__all__ = ["parse_goal"]
