"""Centered arrow-key pickers for the TUI.

Two pickers live here:

* :func:`pick` — a simple radiolist used by the misc ``/...`` slash commands
  that need a single-pane selector. Built on prompt_toolkit's
  ``radiolist_dialog`` so it themes + scrolls for free.

* :func:`pick_provider_model` — the ``/model`` picker. A two-stage
  drill-down (Stage 1: pick a provider → Stage 2: pick a model under it)
  rendered as a bordered panel with a ``❯`` cursor, ported from Nous
  Hermes's ``_get_model_picker_display`` in ``hermes-agent/cli.py``. The
  panel-rendering helpers (:func:`_panel_box_width`,
  :func:`_append_panel_line`, …) are lifted near-verbatim so the visual
  output matches Hermes line-for-line.
"""

from __future__ import annotations

import shutil
import textwrap
from typing import Any, Sequence


def pick(
    title: str,
    options: list[tuple[Any, str]],
    *,
    text: str = "",
    default: Any = None,
) -> Any:
    """Show a centered single-select picker.

    ``options`` is ``[(value, label), …]``. ``default`` pre-selects a
    value (the highlight starts there). Returns the chosen value, or
    ``None`` if the user cancels (Esc) or a dialog can't be built (no
    TTY). Call it only when no other prompt is on screen — it runs its
    own prompt_toolkit application."""
    if not options:
        return None
    try:
        from prompt_toolkit.shortcuts import radiolist_dialog
        from prompt_toolkit.styles import Style
    except Exception:  # noqa: BLE001
        return None
    style = Style.from_dict({
        "dialog":             "bg:default",
        "dialog.body":        "bg:default",
        "dialog frame.label": "fg:ansibrightblue bold",
        "dialog.body radiolist": "bg:default",
        "radio-selected":     "fg:ansibrightblue bold",
        "radio-checked":      "fg:ansibrightblue bold",
        "button.focused":     "bg:ansibrightblue fg:ansiblack",
    })
    kwargs: dict[str, Any] = dict(
        title=title, text=text, values=options, style=style)
    if default is not None and any(v == default for v, _ in options):
        kwargs["default"] = default
    try:
        return radiolist_dialog(**kwargs).run()
    except Exception:  # noqa: BLE001
        return None


# ── Hermes-style panel helpers ───────────────────────────────────────
# Lifted from hermes-agent/cli.py (the _panel_box_width / _wrap_panel_text /
# _append_panel_line / _append_blank_panel_line trio used by every Hermes
# modal panel — clarify, approval, /model picker) so Jaeger's bordered
# panels render identically.


def _panel_box_width(
    title_text: str, content_lines: Sequence[str],
    min_width: int = 56, max_width: int = 86,
) -> int:
    term_cols = shutil.get_terminal_size((100, 20)).columns
    longest = max(
        [len(title_text)] + [len(line) for line in content_lines]
        + [min_width - 4]
    )
    inner = min(max(longest + 4, min_width - 2), max_width - 2, max(24, term_cols - 6))
    return inner + 2


def _wrap_panel_text(
    text: str, width: int, subsequent_indent: str = "",
) -> list[str]:
    wrapped = textwrap.wrap(
        text, width=max(8, width),
        replace_whitespace=False, drop_whitespace=False,
        subsequent_indent=subsequent_indent,
    )
    return wrapped or [""]


def _append_panel_line(
    lines: list[tuple[str, str]], border_style: str,
    content_style: str, text: str, box_width: int,
) -> None:
    inner_width = max(0, box_width - 2)
    lines.append((border_style, "│ "))
    lines.append((content_style, text.ljust(inner_width)))
    lines.append((border_style, " │\n"))


def _append_blank_panel_line(
    lines: list[tuple[str, str]], border_style: str, box_width: int,
) -> None:
    lines.append((border_style, "│" + (" " * box_width) + "│\n"))


def _compute_picker_viewport(
    selected: int, scroll_offset: int, n: int, term_rows: int,
    *, reserved_below: int = 6, panel_chrome: int = 6, min_visible: int = 3,
) -> tuple[int, int]:
    """Resolve (scroll_offset, visible) for the picker viewport.

    Lifted from Hermes's ``_compute_model_picker_viewport`` so the scroll
    behaviour matches: keeps ``selected`` on screen, slides the offset only
    far enough to bring it back."""
    max_visible = max(min_visible, term_rows - reserved_below - panel_chrome)
    if n <= max_visible:
        return 0, n
    visible = max_visible
    if selected < scroll_offset:
        scroll_offset = selected
    elif selected >= scroll_offset + visible:
        scroll_offset = selected - visible + 1
    scroll_offset = max(0, min(scroll_offset, n - visible))
    return scroll_offset, visible


# ── two-stage /model picker — Hermes-faithful drill-down ─────────────


def _render_model_picker(
    state: dict[str, Any], term_rows: int,
) -> list[tuple[str, str]]:
    """Build one frame of the two-stage picker. Mirrors Hermes's
    ``_get_model_picker_display`` line-for-line."""
    stage = state.get("stage", "provider")
    if stage == "provider":
        title = "⚙ Model Picker — Select Provider"
        providers = state.get("providers") or []
        choices: list[str] = []
        for p in providers:
            models = p.get("models") or []
            if p.get("type_a_model"):
                label = f"{p['name']} (type a model)"
            else:
                count = p.get("total_models", len(models))
                label = f"{p['name']} ({count} model{'s' if count != 1 else ''})"
            if p.get("is_current"):
                label += "  ← current"
            choices.append(label)
        choices.append("Cancel")
        hint = (
            f"Current: {state.get('current_model') or 'unknown'} on "
            f"{state.get('current_provider') or 'unknown'}"
        )
    else:
        provider_data = state.get("provider_data") or {}
        model_list = state.get("model_list") or []
        title = f"⚙ Model Picker — {provider_data.get('name', provider_data.get('slug', 'Provider'))}"
        choices = list(model_list) + ["← Back", "Cancel"]
        if model_list:
            hint = f"Select a model ({len(model_list)} available)"
        else:
            hint = "No models listed for this provider. Use Back or Cancel."

    box_width = _panel_box_width(title, [hint] + choices, min_width=46, max_width=84)
    inner_text_width = max(8, box_width - 6)
    selected = state.get("selected", 0)

    scroll_offset, visible = _compute_picker_viewport(
        selected, state.get("_scroll_offset", 0), len(choices), term_rows,
    )
    state["_scroll_offset"] = scroll_offset

    lines: list[tuple[str, str]] = []
    lines.append(("class:picker.border", "╭─ "))
    lines.append(("class:picker.title", title))
    lines.append(("class:picker.border",
                  " " + ("─" * max(0, box_width - len(title) - 3)) + "╮\n"))
    _append_blank_panel_line(lines, "class:picker.border", box_width)
    _append_panel_line(lines, "class:picker.border", "class:picker.hint", hint, box_width)
    _append_blank_panel_line(lines, "class:picker.border", box_width)
    for idx in range(scroll_offset, scroll_offset + visible):
        choice = choices[idx]
        style = "class:picker.selected" if idx == selected else "class:picker.choice"
        prefix = "❯ " if idx == selected else "  "
        for wrapped in _wrap_panel_text(prefix + choice, inner_text_width, subsequent_indent="  "):
            _append_panel_line(lines, "class:picker.border", style, wrapped, box_width)
    _append_blank_panel_line(lines, "class:picker.border", box_width)
    lines.append(("class:picker.border", "╰" + ("─" * box_width) + "╯\n"))
    return lines


_PICKER_TYPE_A_MODEL = object()
"""Sentinel returned in place of a model name when the user picked a
type-a-model provider — the caller prompts the user for a typed model name."""


def _handle_picker_enter(state: dict[str, Any]) -> tuple[bool, Any]:
    """Process Enter on the current ``state``. Returns ``(done, result)`` —
    ``done=True`` exits the picker with ``result`` (a (slug, model) tuple
    or ``None``); ``done=False`` mutates ``state`` for the next stage and
    keeps the picker open. Mirrors Hermes's ``_handle_model_picker_selection``."""
    selected = state.get("selected", 0)
    stage = state.get("stage", "provider")
    if stage == "provider":
        providers = state.get("providers") or []
        if selected >= len(providers):                       # Cancel
            return True, None
        chosen = providers[selected]
        if chosen.get("type_a_model"):
            return True, (chosen["slug"], _PICKER_TYPE_A_MODEL)
        # Drill into stage 2.
        state["stage"] = "model"
        state["provider_data"] = chosen
        state["model_list"] = list(chosen.get("models") or [])
        state["selected"] = 0
        state["_scroll_offset"] = 0
        return False, None
    # stage == "model"
    model_list = state.get("model_list") or []
    back_idx = len(model_list)
    cancel_idx = back_idx + 1
    if selected == back_idx:                                 # ← Back
        providers = state.get("providers") or []
        slug = (state.get("provider_data") or {}).get("slug")
        prev_idx = next(
            (i for i, p in enumerate(providers) if p.get("slug") == slug), 0,
        )
        state["stage"] = "provider"
        state["selected"] = prev_idx
        state["_scroll_offset"] = 0
        state["provider_data"] = None
        state["model_list"] = None
        return False, None
    if selected >= cancel_idx:                               # Cancel
        return True, None
    return True, ((state["provider_data"] or {}).get("slug"), model_list[selected])


def _picker_max_index(state: dict[str, Any]) -> int:
    """Last valid index on the current stage (Cancel / Back+Cancel rows)."""
    if state.get("stage") == "provider":
        return len(state.get("providers") or [])
    return len(state.get("model_list") or []) + 1


def pick_provider_model(
    providers: list[dict[str, Any]],
    *,
    current_provider: str = "",
    current_model: str = "",
) -> tuple[str, Any] | None:
    """A two-stage Hermes-style ``/model`` picker.

    ``providers`` is the stage-1 list — each item is a dict with
    ``slug``, ``name``, ``models`` (list of model-name strings), optional
    ``total_models``, ``is_current``, and ``type_a_model`` (bool — when
    True the provider has no catalogue and Enter returns
    ``(slug, _PICKER_TYPE_A_MODEL)`` so the caller can prompt for a typed
    model name).

    Returns ``(provider_slug, model)`` on selection, or ``None`` on
    cancel / no TTY. ``model`` is :data:`_PICKER_TYPE_A_MODEL` when the
    user picked a type-a-model provider.
    """
    if not providers:
        return None
    try:
        from prompt_toolkit import Application
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style
    except Exception:  # noqa: BLE001
        return None

    default_idx = next(
        (i for i, p in enumerate(providers) if p.get("is_current")), 0,
    )
    state: dict[str, Any] = {
        "stage": "provider",
        "providers": providers,
        "selected": default_idx,
        "current_model": current_model,
        "current_provider": current_provider,
        "_scroll_offset": 0,
        "provider_data": None,
        "model_list": None,
    }

    def _term_rows() -> int:
        try:
            from prompt_toolkit.application import get_app
            return get_app().output.get_size().rows
        except Exception:  # noqa: BLE001
            return shutil.get_terminal_size((100, 24)).lines

    def _render() -> FormattedText:
        return FormattedText(_render_model_picker(state, _term_rows()))

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):  # noqa: ARG001
        state["selected"] = max(0, state.get("selected", 0) - 1)

    @kb.add("down")
    def _down(event):  # noqa: ARG001
        state["selected"] = min(_picker_max_index(state), state.get("selected", 0) + 1)

    @kb.add("home")
    def _home(event):  # noqa: ARG001
        state["selected"] = 0

    @kb.add("end")
    def _end(event):  # noqa: ARG001
        state["selected"] = _picker_max_index(state)

    @kb.add("enter")
    @kb.add("c-m")
    @kb.add("c-j")
    def _enter(event):
        done, result = _handle_picker_enter(state)
        if done:
            event.app.exit(result=result)

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("c-q")
    def _cancel(event):
        event.app.exit(result=None)

    # Jaeger-blue accent matching the existing picker theme.
    style = Style.from_dict({
        "picker.border":   "fg:ansibrightblue",
        "picker.title":    "fg:ansibrightblue bold",
        "picker.hint":     "fg:ansibrightblack italic",
        "picker.choice":   "",
        "picker.selected": "fg:ansiblack bg:ansibrightblue bold",
    })
    control = FormattedTextControl(
        _render, focusable=True, show_cursor=False, key_bindings=kb,
    )
    layout = Layout(Window(control, wrap_lines=False, always_hide_cursor=True))
    try:
        return Application(
            layout=layout, style=style,
            full_screen=True, mouse_support=False,
        ).run()
    except Exception:  # noqa: BLE001
        return None
