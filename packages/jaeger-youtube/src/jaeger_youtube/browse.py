"""Supervised, read-only YouTube browsing over Jaeger's Gateway-owned browser.

This module reuses the existing ``packages/jaeger-browser`` worker (Steel
Browser adapter exposing ``POST /jaeger/action``) instead of adding a second
browser stack. It adds a browser supervision layer:

* **Owner approval per action** — every mutating action (navigate, scroll)
  must carry the token returned by :meth:`YouTubeBrowserSession.approve`.
* **Visible stop control** — :meth:`YouTubeBrowserSession.stop` latches the
  session; every later action fails closed with ``BrowserStopped``.
* **E-Stop honored** — an injected ``estop_active`` callable (wired to the
  orchestration governor's snapshot) makes every action fail closed while
  latched.
* **Read-only observations** — :meth:`YouTubeBrowserSession.observe` only
  ever sends the worker's ``snapshot`` action; page content is returned as
  untrusted data, never executed as instructions.
* **Credentials stay in the browser** — the worker runs against its own
  Chromium profile; this module never reads, exports, or sends cookies or
  sign-in state. Navigation is restricted to YouTube hosts.

The worker's bearer token is a Jaeger-internal localhost credential, not a
YouTube credential.
"""

from __future__ import annotations

import secrets
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

__all__ = [
    "ApprovalError",
    "BrowserStopped",
    "BrowserWorkerError",
    "EStopActive",
    "NavigationNotAllowed",
    "YOUTUBE_HOSTS",
    "BrowserWorkerClient",
    "YouTubeBrowserSession",
]

YOUTUBE_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
)


class BrowserWorkerError(RuntimeError):
    """The browser worker rejected or failed an action."""


class ApprovalError(BrowserWorkerError):
    """Action attempted without a valid owner approval token."""


class BrowserStopped(BrowserWorkerError):
    """The visible stop control was engaged; the session is latched off."""


class EStopActive(BrowserWorkerError):
    """The governor E-Stop is latched; all browser actions fail closed."""


class NavigationNotAllowed(BrowserWorkerError):
    """URL is outside the YouTube host allowlist."""


class _ActionClient(Protocol):
    def action(self, body: dict[str, Any]) -> dict[str, Any]: ...


class BrowserWorkerClient:
    """Minimal bearer-authenticated client for the Gateway-owned browser worker."""

    def __init__(self, port: int, token: str, timeout: float = 30.0) -> None:
        if not token:
            raise ValueError("browser worker token must not be empty")
        self._base = f"http://127.0.0.1:{int(port)}"
        self._token = token
        self._timeout = timeout

    def action(self, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self._base}/jaeger/action",
            data=__import__("json").dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return __import__("json").load(response)
        except HTTPError as exc:
            detail = ""
            with exc:
                try:
                    detail = exc.read().decode("utf-8", "replace")[:500]
                except Exception:  # noqa: BLE001
                    detail = ""
            raise BrowserWorkerError(f"worker HTTP {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise BrowserWorkerError(f"worker unreachable at {self._base}: {exc.reason}") from exc


class YouTubeBrowserSession:
    """One supervised browsing session in an owner-authorized tab.

    ``estop_active`` should be wired to the governor, e.g.
    ``lambda: bool(governor.snapshot().get("estop_active"))``.
    """

    def __init__(
        self,
        client: _ActionClient,
        *,
        estop_active: Callable[[], bool] = lambda: False,
        page_id: str | None = None,
    ) -> None:
        self._client = client
        self._estop_active = estop_active
        self._page_id = page_id
        self._approval: str | None = None
        self._stopped = False

    # -- supervision -----------------------------------------------------

    def approve(self, reason: str = "owner_authorized_youtube_browse") -> str:
        """Owner approval: returns the token required by every mutating action."""
        if self._stopped:
            raise BrowserStopped("session is stopped; open a new session to browse again")
        self._approval = f"{reason}:{secrets.token_hex(16)}"
        return self._approval

    def stop(self) -> None:
        """Visible stop control: latch the session off. Irreversible for this session."""
        self._stopped = True
        self._approval = None

    @property
    def stopped(self) -> bool:
        return self._stopped

    def _guard(self, approval: str | None) -> None:
        if self._stopped:
            raise BrowserStopped("stop control engaged; no further browser actions")
        if self._estop_active():
            raise EStopActive("governor estop_active; browser actions fail closed")
        if approval is None or approval != self._approval:
            raise ApprovalError("missing or invalid owner approval token for this action")

    def _act(self, body: dict[str, Any], *, approval: str | None = None) -> dict[str, Any]:
        self._guard(approval)
        if self._page_id:
            body = {"page_id": self._page_id, **body}
        return self._client.action(body)

    # -- actions ---------------------------------------------------------

    def open(self, url: str, *, approval: str) -> dict[str, Any]:
        """Navigate the authorized tab to a YouTube URL (host allowlist enforced)."""
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
            raise NavigationNotAllowed(f"only YouTube hosts are allowed, got: {host or url!r}")
        return self._act({"action": "navigate", "url": url}, approval=approval)

    def scroll_once(self, direction: str = "down", *, approval: str) -> dict[str, Any]:
        """Scroll exactly one step, then return a read-only snapshot of what is visible."""
        if direction not in {"up", "down"}:
            raise ValueError("direction must be 'up' or 'down'")
        result = self._act({"action": "scroll", "direction": direction}, approval=approval)
        return self.observe()

    # -- read-only observation -------------------------------------------

    def observe(self) -> dict[str, Any]:
        """Read-only snapshot of the current tab. Never mutates the page."""
        if self._stopped:
            raise BrowserStopped("stop control engaged; no further browser actions")
        if self._estop_active():
            raise EStopActive("governor estop_active; browser actions fail closed")
        body: dict[str, Any] = {"action": "snapshot"}
        if self._page_id:
            body["page_id"] = self._page_id
        return self._client.action(body)
