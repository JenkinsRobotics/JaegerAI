"""Zero-dependency Python SDK client for talking to a live JaegerAI Gateway.

Inspired by JROS's single-file ``jros_client.py``: pure Python stdlib
(``urllib.request`` + ``json``) so sibling apps (JaegerAvatar, JaegerArena,
AetherStudio, JP01 scripts, notebooks) can embed or query JaegerAI in one import.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request


class JaegerClientError(RuntimeError):
    """Raised when the JaegerAI Gateway returns an HTTP or transport error."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class JaegerClient:
    """Lightweight stdlib client for the JaegerAI Gateway HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        token: str | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        raw_url = (base_url or os.environ.get("JAEGER_GATEWAY_URL") or "http://127.0.0.1:33418").strip()
        self.base_url = raw_url.rstrip("/")
        self.token = (token or os.environ.get("JAEGER_GATEWAY_TOKEN") or "").strip()
        self.timeout_s = max(1.0, float(timeout_s))

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        extra_headers: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json", "User-Agent": "JaegerClient/1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra_headers:
            headers.update({str(k): str(v) for k, v in extra_headers.items()})
        data: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=float(timeout_s or self.timeout_s)) as resp:
                raw = resp.read(2_000_000).decode("utf-8", errors="replace")
                parsed = json.loads(raw) if raw.strip() else {}
                return parsed if isinstance(parsed, dict) else {"data": parsed}
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(4096).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
            raise JaegerClientError(f"HTTP {exc.code} on {method} {path}: {detail or exc.reason}", status=int(exc.code)) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise JaegerClientError(f"Cannot reach JaegerAI Gateway at {self.base_url}: {exc}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def models(self) -> dict[str, Any]:
        return self._request("GET", "/v1/models")

    def cookbook(self, *, modality: str = "all", ram_gb: float | None = None) -> dict[str, Any]:
        params: dict[str, str] = {"modality": modality}
        if ram_gb is not None:
            params["ram_gb"] = str(ram_gb)
        return self._request("GET", f"/v1/models/cookbook?{urllib.parse.urlencode(params)}")

    def ask(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        model: str = "jaeger",
        timeout_s: float = 120.0,
    ) -> str:
        """Send a single-turn chat prompt via OpenAI-compatible ``/v1/chat/completions``."""
        headers = {"X-Jaeger-Session-Id": session_id} if session_id else None
        res = self._request(
            "POST",
            "/v1/chat/completions",
            {"model": model, "stream": False, "messages": [{"role": "user", "content": prompt}]},
            extra_headers=headers,
            timeout_s=timeout_s,
        )
        choices = res.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            return str(msg.get("content") or "")
        return ""

    def get_mode(self) -> str:
        return str(self._request("GET", "/v1/system/mode").get("mode") or "build")

    def set_mode(self, mode: str) -> dict[str, Any]:
        return self._request("POST", "/v1/system/mode", {"mode": mode})

    def roundtable(
        self,
        prompt: str,
        *,
        models: list[str] | None = None,
        blind: bool = False,
        consensus: bool = True,
        timeout_s: float = 180.0,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/models/roundtable",
            {"prompt": prompt, "models": models or [], "blind": blind, "consensus": consensus},
            timeout_s=timeout_s,
        )

    def research(self, topic: str, *, max_queries: int = 3, max_sources: int = 6, timeout_s: float = 180.0) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/research/run",
            {"topic": topic, "max_queries": max_queries, "max_sources": max_sources},
            timeout_s=timeout_s,
        )

    def board(self) -> dict[str, Any]:
        return self._request("GET", "/v1/board")

    def add_card(self, title: str, *, column: str = "todo", priority: int = 2, notes: str = "") -> dict[str, Any]:
        return self._request("POST", "/v1/board/cards", {"title": title, "column": column, "priority": priority, "notes": notes})

    def remind_in(self, minutes: float, message: str) -> dict[str, Any]:
        return self._request("POST", "/v1/reminders", {"message": message, "in_minutes": minutes})

    def avatar_packs(self) -> dict[str, Any]:
        return self._request("GET", "/v1/avatars/packs")

    def nexus_jp01_channels(self) -> dict[str, Any]:
        return self._request("GET", "/v1/hardware/nexus/jp01-channels")

    def nexus_snapshot(self, station_url: str = "http://127.0.0.1:8000") -> dict[str, Any]:
        qs = urllib.parse.urlencode({"station_url": station_url})
        return self._request("GET", f"/v1/hardware/nexus/snapshot?{qs}")

    def model_telemetry(self, *, window_days: float = 7.0, live: bool = True) -> dict[str, Any]:
        qs = urllib.parse.urlencode({"window_days": window_days, "live": str(live).lower()})
        return self._request("GET", f"/v1/models/telemetry?{qs}")

    def model_risk_cards(self, *, model: str | None = None) -> dict[str, Any]:
        path = "/v1/models/risk-cards"
        if model:
            path += "?" + urllib.parse.urlencode({"model": model})
        return self._request("GET", path)

    def model_eval(self, models: list[str], *, timeout_s: float = 180.0) -> dict[str, Any]:
        return self._request("POST", "/v1/models/eval", {"models": models}, timeout_s=timeout_s)

    def remote_discover(self) -> dict[str, Any]:
        return self._request("GET", "/v1/remote/discover")

    def remote_connect(self, target: str, *, alias: str = "", user: str = "", probe: bool = True) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/remote/connect",
            {"target": target, "alias": alias, "user": user, "probe": probe},
        )


__all__ = ["JaegerClient", "JaegerClientError"]
