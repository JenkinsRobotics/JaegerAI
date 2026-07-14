"""macOS host control — one tool, ``open_on_host``.

Three near-identical wrappers around the macOS ``open`` command
(launch a URL, open a workspace file, launch an app) used to be three
separate tools. They are one now: ``open_on_host(target)`` auto-detects
which kind of target it got, so the agent has a single, unambiguous
verb for "put this in front of the user."

File targets are sandbox-resolved to <instance>/skills/ (the agent's
writable area) — only files the agent itself authored, or that already
live in skills/, can be opened.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_ai.agent.tools.time_and_math import system_status
from jaeger_ai.core.context import SandboxError, _require_layout, _resolve_under
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier


def _run_open(args: list[str], label: dict[str, Any]) -> dict[str, Any]:
    """Run ``open`` with ``args``; fold the result into ``label``."""
    if platform.system() != "Darwin":
        return {"error": f"open_on_host only supported on macOS (got {platform.system()})", **label}
    try:
        result = subprocess.run(["open", *args], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], **label}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), **label}
    return {"opened": True, **label}


def open_on_host(target: str, kind: str = "auto", app: str = "") -> dict[str, Any]:
    """Open a URL, a workspace file, or a macOS app on the host.

    ``kind`` is one of ``"auto"`` (default), ``"url"``, ``"file"``,
    ``"app"``. With ``"auto"`` the target is classified:

      • starts with http:// or https://  → opened as a URL
      • resolves to an existing file under skills/ → opened as a file
      • otherwise → treated as an app name (``open -a``)

    ``app`` (URL targets only) names the app to open the URL in
    (``open -a <app> <url>``), e.g. "Safari"; empty = default browser.
    """
    clean = (target or "").strip()
    if not clean:
        return {"error": "empty target"}
    kind = (kind or "auto").strip().lower()

    is_url = clean.startswith("http://") or clean.startswith("https://")
    if kind == "auto":
        if is_url:
            kind = "url"
        else:
            # File if it resolves inside skills/ and exists; else app.
            try:
                layout = _require_layout()
                resolved = _resolve_under(layout.skills_dir, clean)
                kind = "file" if resolved.exists() else "app"
            except (SandboxError, Exception):  # noqa: BLE001
                kind = "app"

    if kind == "url":
        if not is_url:
            return {"error": "URL must start with http:// or https://", "url": clean}
        app = (app or "").strip()
        if app:
            return _run_open(["-a", app, clean], {"url": clean, "app": app})
        return _run_open([clean], {"url": clean})

    if kind == "file":
        layout = _require_layout()
        try:
            resolved = _resolve_under(layout.skills_dir, clean)
        except SandboxError as exc:
            return {"error": str(exc), "path": clean}
        if not resolved.exists():
            return {"error": "file not found", "path": clean}
        return _run_open([str(resolved)], {"path": str(resolved.relative_to(layout.root))})

    if kind == "app":
        return _run_open(["-a", clean], {"app": clean})

    return {"error": f"unknown kind {kind!r} (use auto/url/file/app)", "target": clean}


@register_tool_from_function(name="system_status", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="host", operation="system_status",
               summary="read machine + instance dir status")
def _t_system_status() -> dict:
    """Machine health only: CPU, memory, disk, and instance metadata.
    Do NOT use this to list workspace files; use list_skill_dir for
    "list the workspace", "show files", or "what files are here"."""
    return system_status()


@register_tool_from_function(name="open_on_host")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="host",
               operation="open_on_host",
               summary="open a URL / file / app on the host")
def _t_open_on_host(target: str, kind: str = "auto", app: str = "") -> dict:
    """Open something on the host (macOS) — the FIRST tool for any
    "open / launch / pull up X" ask. One verb for three cases: a URL
    in the browser, a workspace file in its default app, or a macOS
    application by name. "open youtube in safari" = ONE call:
    target="https://www.youtube.com", app="Safari" — never drive the
    GUI (computer_open_app / computer_use) just to open a website.
    `app` (URLs only) picks the browser; empty = system default.
    `kind` is "auto" (default), "url", "file", or "app" — "auto"
    classifies the target (http → URL, an existing skills/ file →
    file, else → app name). File targets are sandbox-resolved under
    <instance>/skills/."""
    return open_on_host(target=target, kind=kind, app=app)


@register_tool_from_function(name="set_mode")
def _t_set_mode(mode: str) -> dict:
    """Switch the agent's runtime mode — model + voice profile:
      • normal — small fast model (gemma-12B) + voice (the default)
      • high — larger model (gemma-26B), voice off; heavier reasoning
      • deep-sleep — high model + work the Deep Think queue
    Use when the user asks to switch ("use the bigger model", "go high
    agentic mode", "back to normal mode"). The model swap is SLOW (~60-90s)
    — tell the user it's switching, it's not stuck. Returns {ok, mode,
    model, voice} or {ok:false, error}."""
    from jaeger_ai.core.runtime.modes import set_mode as _set_mode
    return _set_mode(mode)


@register_tool_from_function(name="get_mode", side_effect="read")
def _t_get_mode() -> dict:
    """Report the agent's CURRENT runtime mode + its model/voice profile —
    use this to answer "what mode are you in?" / "which model is running?"
    from fact, never guess. Returns {mode, model, voice, options}."""
    from jaeger_ai.core.runtime.modes import mode_info
    return mode_info()


@register_tool_from_function(name="set_autonomy")
def _t_set_autonomy(mode: str) -> dict:
    """Set how autonomously you EXECUTE once a task is agreed:
      • ask    — pause for approval before EVERY outward/hardware/destructive action
      • scoped — agree the risky scope up front, then run autonomously within it;
                 anything new prompts once, out-of-scope or missing info → ask (default)
      • auto   — fully autonomous: act without pausing, reach out only when blocked
    The PLAN is settled up front regardless; this governs execution only.
    Switching is INSTANT (no model swap). Returns {ok, mode} or {ok:false,
    error}."""
    from jaeger_ai.core.runtime.autonomy import set_autonomy as _set_autonomy
    return _set_autonomy(mode)


@register_tool_from_function(name="get_autonomy", side_effect="read")
def _t_get_autonomy() -> dict:
    """Report your CURRENT autonomy mode (ask | scoped | auto) — answer "how
    autonomous are you / will you ask before acting?" from fact, never guess.
    Returns {autonomy, options, description}."""
    from jaeger_ai.core.runtime.autonomy import autonomy_info
    return autonomy_info()
