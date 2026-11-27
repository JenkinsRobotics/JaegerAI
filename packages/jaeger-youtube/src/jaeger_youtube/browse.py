"""HTTP transport shared by Gateway browser supervision."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BrowserWorkerError(RuntimeError):
    """A request to the local browser worker failed."""


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
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return json.load(response)
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
