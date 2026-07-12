"""Accessibility-tree engine — focus-preserving Mac control.

The bottom-right tier of the capability ladder before vision. The
Accessibility API talks to the **object tree** macOS exposes for
every app that participates (which is most): windows, buttons,
fields, menus, with roles + labels + values. We:

  * read attributes (``AXTitle``, ``AXValue``, ``AXPosition``)
  * invoke actions (``AXPress`` to click a button)
  * mutate values (``AXSetValue`` to fill a text field)
  * move/resize windows (``AXPosition`` / ``AXSize`` write)

without moving the mouse and without stealing keyboard focus. That
makes it the right engine for any UI op where the target element is
labelled — and on macOS, ~80% of apps expose enough AX to drive
common workflows.

Salvaged from the retired ``computer_use_v2/macos_background.py``; the
low-level helpers live in :mod:`._ax_lowlevel` so this file can
stay focused on the Engine protocol surface.
"""

from __future__ import annotations

import time
from typing import Any

from jaeger_ai.agent.skills.macos_computer_v1.engines import Action, Engine, EngineResult


_NAME = "ax"
_PRIORITY = 30  # third in the ladder: applescript(10) < browser(20) < ax(30) < vision(90)


class AXEngine:
    """Engine protocol implementation around the low-level AX helpers.

    ``can_handle`` claims confidence on the kinds the low-level
    module already implements: ``press`` (AXPress on a labelled
    element), ``move_window``, ``resize_window``, ``list_windows``,
    ``list_apps``, ``read_ax_tree``. Anything else falls through to
    the next tier.
    """

    name: str = _NAME
    priority: int = _PRIORITY

    def is_available(self) -> tuple[bool, str]:
        """Delegate to the low-level availability probe — checks
        PyObjC importability + the Accessibility permission state."""
        from jaeger_ai.agent.skills.macos_computer_v1.engines import _ax_lowlevel
        return _ax_lowlevel.is_available()

    def can_handle(self, action: Action) -> float:
        """Confidence map per action kind. Tuned conservatively —
        we'd rather fall through to vision than blow a wrong click."""
        kind = (action.kind or "").lower()
        if kind in ("press", "click_label", "click_element"):
            # AX press is the highest-confidence path when the target
            # carries a label/role pair.
            return 0.9 if action.args.get("label") else 0.3
        if kind in ("type", "set_value"):
            return 0.85 if action.args.get("label") else 0.3
        if kind in ("move_window", "resize_window"):
            return 0.95
        if kind in ("list_windows", "list_apps", "read_ax_tree"):
            return 1.0
        if kind == "raise_window":
            return 0.9
        if kind in ("read_value", "ax_read", "get_value"):
            # Fast object-state read — the verification path.
            return 0.95
        if kind in ("focused_window", "current_window", "look"):
            return 0.95
        if kind in ("menu_select", "menu", "select_menu"):
            # Path through the AX menu bar — covers File / Edit /
            # View / Window menus across every native app.
            return 0.95 if action.args.get("path") else 0.3
        # Click by (x, y) is a vision-engine job. Open-app is
        # applescript's lane. We don't claim those.
        return 0.0

    def execute(self, action: Action) -> EngineResult:
        from jaeger_ai.agent.skills.macos_computer_v1.engines import _ax_lowlevel as ax
        started = time.perf_counter()
        kind = (action.kind or "").lower()
        args = action.args or {}
        try:
            if kind in ("press", "click_label", "click_element"):
                result = ax.press_element(
                    app=action.target or args.get("app") or "",
                    label=args.get("label", ""),
                    role=args.get("role", ""),
                )
            elif kind in ("type", "set_value"):
                # Set the value attribute on a labelled field — same
                # element lookup as press, different write.
                result = _ax_set_value(
                    app=action.target or args.get("app") or "",
                    label=args.get("label", ""),
                    value=str(args.get("value", "")),
                )
            elif kind == "move_window":
                result = ax.move_window(
                    app=action.target or args.get("app") or "",
                    x=float(args.get("x", 0)),
                    y=float(args.get("y", 0)),
                    window_index=int(args.get("window_index", 0)),
                )
            elif kind == "resize_window":
                result = ax.resize_window(
                    app=action.target or args.get("app") or "",
                    width=float(args.get("width", 0)),
                    height=float(args.get("height", 0)),
                    window_index=int(args.get("window_index", 0)),
                )
            elif kind == "list_windows":
                result = ax.list_windows(app=action.target or args.get("app") or "")
            elif kind == "list_apps":
                result = ax.list_running_apps()
            elif kind in ("read_value", "ax_read", "get_value"):
                result = ax_read_value(
                    app=action.target or args.get("app") or "",
                    label=args.get("label", ""),
                    role=args.get("role", ""),
                )
            elif kind in ("focused_window", "current_window", "look"):
                result = ax_focused_window(
                    app=action.target or args.get("app") or "",
                )
            elif kind in ("menu_select", "menu", "select_menu"):
                result = ax_menu_select(
                    app=action.target or args.get("app") or "",
                    path=args.get("path", ""),
                )
            else:
                return EngineResult(
                    ok=False, engine=_NAME,
                    error=f"ax_engine does not handle kind={kind!r}",
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                )
        except Exception as exc:  # noqa: BLE001 — engine must never raise
            return EngineResult(
                ok=False, engine=_NAME,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
        ok = bool(result.get("ok")) if isinstance(result, dict) else False
        return EngineResult(
            ok=ok, engine=_NAME, result=result,
            error="" if ok else str(result.get("error", "") if isinstance(result, dict) else ""),
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )


def _ax_set_value(*, app: str, label: str, value: str) -> dict[str, Any]:
    """Locate ``label`` in ``app``'s AX tree, write ``value`` to its
    ``AXValue`` attribute. Used by the ``type`` / ``set_value``
    action kinds.

    Lives here (not in ``_ax_lowlevel``) because the low-level file
    was salvaged from v2 verbatim; this is the new add."""
    from jaeger_ai.agent.skills.macos_computer_v1.engines import _ax_lowlevel as ax
    ready, detail = ax.is_available()
    if not ready:
        return ax._unavailable(detail)
    pid = ax._resolve_pid(app)
    if pid is None:
        return {"ok": False, "error": f"no running app matches {app!r}"}
    import ApplicationServices as _AX
    target_app = _AX.AXUIElementCreateApplication(pid)
    found = ax._walk(target_app, "AXTextField", label, 0, [ax._MAX_NODES])
    if found is None:
        found = ax._walk(target_app, "AXTextArea", label, 0, [ax._MAX_NODES])
    if found is None:
        return {"ok": False,
                "error": f"no text field labelled {label!r} in {app!r}"}
    err = _AX.AXUIElementSetAttributeValue(found, _AX.kAXValueAttribute, value)
    if err != 0:
        return {"ok": False, "error": ax._ax_err(err)}
    return {"ok": True, "set": value, "label": label, "app": app}


# ── menu walking — File > New, Edit > Copy, etc. ──────────────────


def ax_menu_select(*, app: str, path: str) -> dict[str, Any]:
    """Walk an app's menu bar and AXPress the leaf item named by
    ``path``. ``path`` is ``"File > New"`` / ``"Edit > Copy"`` /
    ``"View > Zoom > Zoom In"`` — ``>`` is the level separator.

    Native menu navigation is much faster than the screenshot loop
    AND it covers the case where the menu item exists but is off-
    screen / cut by app chrome (the menu bar always responds to AX
    even when collapsed).

    Returns ``{ok, app, path, pressed}`` on success or
    ``{ok=False, error}`` with the missing level surfaced so the
    agent can correct."""
    from jaeger_ai.agent.skills.macos_computer_v1.engines import _ax_lowlevel as ax
    ready, detail = ax.is_available()
    if not ready:
        return ax._unavailable(detail)
    if not path:
        return {"ok": False, "error": "menu_select needs a path "
                                       "(e.g. 'File > New')"}
    pid = ax._resolve_pid(app)
    if pid is None:
        return {"ok": False, "error": f"no running app matches {app!r}"}
    import ApplicationServices as _AX
    target_app = _AX.AXUIElementCreateApplication(pid)
    menu_bar = ax._copy_attr(target_app, "AXMenuBar")
    if menu_bar is None:
        return {"ok": False, "error": f"{app!r} has no AX menu bar"}

    levels = [seg.strip() for seg in path.split(">") if seg.strip()]
    if not levels:
        return {"ok": False, "error": f"empty menu path {path!r}"}

    # Start at the menu bar's children (the top-level menus).
    current_children = ax._copy_attr(menu_bar, _AX.kAXChildrenAttribute) or []
    target = None
    for level_idx, name in enumerate(levels):
        match = None
        for child in current_children:
            title = str(ax._copy_attr(child, _AX.kAXTitleAttribute) or "")
            if title.lower() == name.lower():
                match = child
                break
        if match is None:
            crumb = " > ".join(levels[: level_idx + 1])
            return {"ok": False, "error": f"menu level {crumb!r} not found "
                                           f"in {app!r}"}
        target = match
        # Drill into the matched item's submenu for the next level.
        # AppKit nests an AXMenu inside each menu item; walk in.
        if level_idx < len(levels) - 1:
            submenu = ax._copy_attr(match, _AX.kAXChildrenAttribute) or []
            # The submenu is itself an AXMenu element wrapping the items.
            if submenu and len(submenu) == 1:
                axmenu_children = ax._copy_attr(
                    submenu[0], _AX.kAXChildrenAttribute,
                ) or []
                current_children = axmenu_children
            else:
                current_children = submenu

    if target is None:
        return {"ok": False, "error": f"menu walk produced no target for {path!r}"}
    err = _AX.AXUIElementPerformAction(target, _AX.kAXPressAction)
    if err != 0:
        return {"ok": False, "error": ax._ax_err(err)}
    return {"ok": True, "app": app, "path": path, "pressed": True}


# ── READ operations — verification should be cheap ─────────────────


def ax_read_value(*, app: str, label: str = "", role: str = "") -> dict[str, Any]:
    """Read ``AXValue`` from an element identified by ``label`` (and
    optionally ``role``). The fast verification path — "did my
    type/click land?" answered without a screenshot.

    Example: after typing "Hello" into a Notes note, call
    ``ax_read_value(app="Notes", role="AXTextArea")`` to confirm."""
    from jaeger_ai.agent.skills.macos_computer_v1.engines import _ax_lowlevel as ax
    ready, detail = ax.is_available()
    if not ready:
        return ax._unavailable(detail)
    pid = ax._resolve_pid(app)
    if pid is None:
        return {"ok": False, "error": f"no running app matches {app!r}"}
    import ApplicationServices as _AX
    target_app = _AX.AXUIElementCreateApplication(pid)
    found = ax._walk(target_app, role, label, 0, [ax._MAX_NODES])
    if found is None:
        return {"ok": False, "error": f"no element role={role!r} "
                                       f"label={label!r} in {app!r}"}
    value = ax._copy_attr(found, _AX.kAXValueAttribute)
    return {"ok": True, "value": str(value or ""),
            "label": label, "role": role, "app": app}


def ax_focused_window(*, app: str = "") -> dict[str, Any]:
    """The focused window of ``app`` (or the system-wide focused
    window when ``app=""``). Returns title + position + size +
    a SHALLOW element summary (immediate children with their roles
    + titles + first 80 chars of value). Read-only.

    Designed to be the cheap counterpart to a screenshot — the
    agent calls it to see "what's currently on screen" without
    invoking the vision tier."""
    from jaeger_ai.agent.skills.macos_computer_v1.engines import _ax_lowlevel as ax
    ready, detail = ax.is_available()
    if not ready:
        return ax._unavailable(detail)
    import ApplicationServices as _AX
    if app:
        pid = ax._resolve_pid(app)
        if pid is None:
            return {"ok": False, "error": f"no running app matches {app!r}"}
        target_app = _AX.AXUIElementCreateApplication(pid)
        focused = ax._copy_attr(target_app, _AX.kAXFocusedWindowAttribute)
    else:
        # System-wide focused element walks up to its enclosing window.
        system = _AX.AXUIElementCreateSystemWide()
        focused_el = ax._copy_attr(system, _AX.kAXFocusedUIElementAttribute)
        focused = ax._copy_attr(focused_el, _AX.kAXWindowAttribute) \
            if focused_el is not None else None
    if focused is None:
        return {"ok": False, "error": "no focused window"}

    title = str(ax._copy_attr(focused, _AX.kAXTitleAttribute) or "")
    pos, size = ax._point_size(focused)
    # Shallow child summary — roles + titles + truncated values.
    children = ax._copy_attr(focused, _AX.kAXChildrenAttribute) or []
    summary: list[dict[str, str]] = []
    for child in list(children)[:20]:
        summary.append({
            "role": str(ax._copy_attr(child, _AX.kAXRoleAttribute) or ""),
            "title": str(ax._copy_attr(child, _AX.kAXTitleAttribute) or ""),
            "value": str(ax._copy_attr(child, _AX.kAXValueAttribute) or "")[:80],
        })
    return {
        "ok": True,
        "app": app or "(focused)",
        "title": title,
        "position": pos,
        "size": size,
        "children": summary,
    }


__all__ = ["AXEngine", "ax_focused_window", "ax_menu_select", "ax_read_value"]
