"""Browser automation — one consolidated tool over a real Chromium.

``browser(action=...)`` drives a live browser via Playwright:

  - open / navigate — load a URL (returns the page's elements)
  - snapshot        — re-list the current page's interactive elements
  - click           — click element N (index from the latest snapshot)
  - type            — type text into element N
  - scroll          — scroll the page up / down
  - back            — go back one page
  - press           — press a key (Enter, Tab, …)
  - close           — close the browser session

Playwright's sync API may not run inside an asyncio loop, and the agent
loop is async — so the whole Playwright session lives in ONE dedicated
worker thread and the tool hands it commands over a queue. The browser
stays alive across calls: open → snapshot → click → type is one session.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_agent.util.tool_interrupt import is_interrupted
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier


def _headless() -> bool:
    """Headed by default so the user can watch the page (e.g. a video
    play). ``JAEGER_BROWSER_HEADLESS=1`` forces headless — tests, or a
    machine with no display."""
    return os.environ.get("JAEGER_BROWSER_HEADLESS", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


# Selector for the elements worth handing the model — clickable / typable.
_INTERACTIVE = (
    "a, button, input, textarea, select, "
    "[role=button], [role=link], [role=tab], [role=menuitem], "
    "[role=checkbox], [role=searchbox], [onclick]"
)
_MAX_ELEMENTS = 60


def _snapshot(page, state: dict[str, Any]) -> dict[str, Any]:
    """Number the page's visible interactive elements; stash their
    handles in ``state`` so a later click/type can resolve an index.
    Also capture full rendered visible text, console errors, and failed requests."""
    try:
        handles = page.query_selector_all(_INTERACTIVE)
    except Exception:
        handles = []
    elements: list[dict[str, Any]] = []
    kept: list[Any] = []
    for h in handles:
        if len(kept) >= _MAX_ELEMENTS:
            break
        try:
            if not h.is_visible():
                continue
        except Exception:
            continue
        label = ""
        for getter in (
            lambda: h.inner_text(timeout=200),
            lambda: h.get_attribute("aria-label"),
            lambda: h.get_attribute("placeholder"),
            lambda: h.get_attribute("value"),
            lambda: h.get_attribute("title"),
        ):
            try:
                label = (getter() or "").strip()
            except Exception:
                label = ""
            if label:
                break
        try:
            tag = (h.evaluate("e => e.tagName") or "").lower()
        except Exception:
            tag = ""
        elements.append({
            "index": len(kept),
            "tag": tag,
            "text": " ".join(label.split())[:80],
        })
        kept.append(h)
    state["handles"] = kept
    try:
        title = page.title()
    except Exception:
        title = ""

    # Capture rendered body text content
    text_content = ""
    try:
        raw_text = page.evaluate("() => document.body ? document.body.innerText : ''")
        text_content = str(raw_text or "").strip()
        if len(text_content) > 8000:
            text_content = text_content[:8000] + "... [truncated]"
    except Exception:
        text_content = ""

    console_errors = [
        item for item in state.get("console_logs", [])
        if str(item.get("type", "")).lower() in ("error", "warning")
    ][-20:]
    failed_reqs = list(state.get("failed_requests", []))[-20:]

    return {
        "url": page.url,
        "title": title,
        "elements": elements,
        "count": len(elements),
        "text_content": text_content,
        "console_errors": console_errors,
        "failed_requests": failed_reqs,
    }


def _element(state: dict[str, Any], index: Any) -> Any:
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return None
    handles = state.get("handles") or []
    return handles[idx] if 0 <= idx < len(handles) else None


def _dispatch(page, state: dict[str, Any], action: str,
              args: dict[str, Any]) -> dict[str, Any]:
    """Run one browser action. Returns a page snapshot, or {"error": …}."""
    if action in ("open", "navigate", "goto", "visit"):
        url = (args.get("url") or "").strip()
        if not url:
            return {"error": "open needs a url"}
        if "://" not in url:
            url = "https://" + url
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(700)
        return _snapshot(page, state)
    if action in ("snapshot", "read", "look", "elements"):
        return _snapshot(page, state)
    if action in ("screenshot", "capture"):
        import base64
        import tempfile
        import time
        path = str(args.get("path") or "").strip()
        if not path:
            path = os.path.join(tempfile.gettempdir(), f"jaeger_browser_{int(time.time() * 1000)}.png")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        page.screenshot(path=path, full_page=bool(args.get("full_page", False)))
        b64 = ""
        size = 0
        try:
            with open(path, "rb") as f:
                img_data = f.read()
                size = len(img_data)
                b64 = base64.b64encode(img_data).decode("ascii")
        except Exception:
            pass
        snap = _snapshot(page, state)
        return {
            "path": path,
            "bytes": size,
            "image_data": b64,
            "image_url": f"data:image/png;base64,{b64}" if b64 else "",
            **snap,
        }
    if action in ("content", "extract_text", "text"):
        snap = _snapshot(page, state)
        return {"text": snap.get("text_content", ""), **snap}
    if action in ("logs", "errors", "console"):
        return {
            "console_logs": list(state.get("console_logs", [])),
            "failed_requests": list(state.get("failed_requests", [])),
        }
    if action == "click":
        h = _element(state, args.get("element"))
        if h is None:
            return {"error": "no element at that index — snapshot first"}
        h.click(timeout=5000)
        page.wait_for_timeout(800)
        return _snapshot(page, state)
    if action in ("type", "fill", "enter"):
        h = _element(state, args.get("element"))
        if h is None:
            return {"error": "no element at that index — snapshot first"}
        h.fill(str(args.get("text", "")))
        return _snapshot(page, state)
    if action == "scroll":
        down = str(args.get("direction", "down")).lower() != "up"
        page.mouse.wheel(0, 800 if down else -800)
        page.wait_for_timeout(400)
        return _snapshot(page, state)
    if action == "back":
        page.go_back(timeout=15000)
        page.wait_for_timeout(500)
        return _snapshot(page, state)
    if action in ("press", "key"):
        page.keyboard.press(str(args.get("key") or "Enter"))
        page.wait_for_timeout(700)
        return _snapshot(page, state)
    return {"error": f"unknown browser action {action!r}"}


class _Session:
    """Owns the Playwright session in one dedicated thread."""

    def __init__(self) -> None:
        self._cmds: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error = ""

    def _loop(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            self._error = (f"Playwright not installed ({exc}) — "
                           "run: pip install playwright && playwright install chromium")
            self._ready.set()
            return
        pw = None
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=_headless())
            page = browser.new_page()
        except Exception as exc:  # noqa: BLE001
            self._error = f"couldn't launch the browser: {exc}"
            self._ready.set()
            if pw is not None:
                try:
                    pw.stop()
                except Exception:  # noqa: BLE001
                    pass
            return

        console_logs: list[dict[str, Any]] = []
        failed_requests: list[dict[str, Any]] = []

        def _on_console(msg: Any) -> None:
            try:
                console_logs.append({
                    "type": str(getattr(msg, "type", "log")),
                    "text": str(getattr(msg, "text", "")),
                    "location": getattr(msg, "location", None),
                })
                if len(console_logs) > 100:
                    console_logs.pop(0)
            except Exception:
                pass

        def _on_req_failed(req: Any) -> None:
            try:
                failed_requests.append({
                    "url": str(getattr(req, "url", "")),
                    "method": str(getattr(req, "method", "GET")),
                    "failure": str(getattr(req, "failure", None)),
                })
                if len(failed_requests) > 100:
                    failed_requests.pop(0)
            except Exception:
                pass

        try:
            page.on("console", _on_console)
            page.on("requestfailed", _on_req_failed)
        except Exception:
            pass

        state: dict[str, Any] = {
            "handles": [],
            "console_logs": console_logs,
            "failed_requests": failed_requests,
        }
        self._ready.set()
        while True:
            action, args, reply = self._cmds.get()
            if action == "_stop":
                try:
                    browser.close()
                    pw.stop()
                except Exception:  # noqa: BLE001
                    pass
                reply.put(("ok", {"closed": True}))
                return
            try:
                reply.put(("ok", _dispatch(page, state, action, args)))
            except Exception as exc:  # noqa: BLE001
                reply.put(("err", f"{type(exc).__name__}: {exc}"))

    def call(self, action: str, args: dict[str, Any],
             timeout: float = 60.0) -> dict[str, Any]:
        if self._thread is None or not self._thread.is_alive():
            self._ready.clear()
            self._error = ""
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="jaeger-browser",
            )
            self._thread.start()
        if not self._ready.wait(timeout=45.0):
            return {"ok": False, "error": "browser failed to start in time"}
        if self._error:
            return {"ok": False, "error": self._error}
        reply: queue.Queue = queue.Queue()
        self._cmds.put((action, args, reply))
        try:
            status, payload = reply.get(timeout=timeout)
        except queue.Empty:
            return {"ok": False, "error": f"browser '{action}' timed out"}
        if status == "err":
            return {"ok": False, "error": payload}
        if isinstance(payload, dict) and payload.get("error"):
            return {"ok": False, "error": payload["error"]}
        return {"ok": True, **(payload or {})}


_session = _Session()


def browser(action: str, url: str = "", element: int = 0, text: str = "",
            direction: str = "down", key: str = "Enter", path: str = "",
            **kwargs: Any) -> dict[str, Any]:
    """Drive a real web browser — ONE tool, action-dispatch.

      - ``open``       — load a URL (``url``); returns the page's elements
      - ``snapshot``   — re-list the current page's interactive elements and rendered text
      - ``screenshot`` — capture screenshot of page to PNG and return path + base64 image data
      - ``content``    — extract visible page text and headings
      - ``errors``     — inspect console errors and failed network requests
      - ``click``      — click element ``element`` (index from a snapshot)
      - ``type``       — type ``text`` into element ``element``
      - ``scroll``     — scroll the page (``direction`` up / down)
      - ``back``       — go back one page
      - ``press``      — press ``key`` (Enter, Tab, …)
      - ``close``      — close the browser

    Every action returns the page's interactive elements, each with an
    ``index`` — click / type by that index. Workflow: open a page, read
    the elements, then click / type by index. The browser stays open
    across calls, so a multi-step task is one running session. Use this
    for the live web — searching visually, playing a video, filling a
    form."""
    act = (action or "").strip().lower()
    if act in ("close", "quit", "shutdown"):
        return _session.call("_stop", {})
    # A Playwright action runs to completion on its worker thread and
    # cannot be interrupted partway. ``close`` is always allowed through
    # (it tears the session down); any other action bails before starting
    # if the turn was already cancelled.
    if is_interrupted():
        return {"ok": False, "interrupted": True,
                "error": "browser action interrupted by user"}
    dispatch_args = {
        "url": url, "element": element, "text": text,
        "direction": direction, "key": key, "path": path,
    }
    dispatch_args.update(kwargs)
    return _session.call(act, dispatch_args)



# ── Agent-tool wrapper (migrated from main.py::_register_builtins) ──


@register_tool_from_function(name="browser", side_effect="external")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="browser",
               operation="browser",
               summary="drive a real web browser")
def _t_browser(action: str, url: str = "", element: int = 0,
               text: str = "", direction: str = "down",
               key: str = "Enter", path: str = "", **kwargs: Any) -> dict:
    """Drive the agent's OWN automation browser (a separate chromium,
    NOT the user's Safari/Chrome) — only for when YOU must read or
    interact with page content (scrape, fill a form, click through a
    flow). "Open <site>" / "open <site> in <browser>" for the USER is
    NEVER this tool — that's one open_on_host call (app="Safari" etc.),
    which uses their real browser. Actions: open / snapshot / click /
    type / scroll / back / press / close / screenshot / content / errors.
    See ``describe_tool("browser")`` for the full action map + args."""
    return browser(action=action, url=url, element=element,
                   text=text, direction=direction, key=key, path=path, **kwargs)
