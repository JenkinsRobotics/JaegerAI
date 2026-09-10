"""Honcho conversational memory bridge for Jaeger AI.

Connects to the Honcho server running locally, on LAN rack (10.15.0.239:8088),
or Tailscale (100.78.245.49:8088).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_HONCHO_URL = "http://10.15.0.239:8088"
DEFAULT_WORKSPACE = "jenkins-robotics"


class HonchoClient:
    """HTTP client for Honcho v3 API with robust serialization."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str = "",
        workspace: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("HONCHO_API_URL") or DEFAULT_HONCHO_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("HONCHO_API_KEY", "")
        self.workspace = workspace or os.environ.get("HONCHO_WORKSPACE") or DEFAULT_WORKSPACE
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            self._headers["Authorization"] = f"Bearer {self.api_key}"

    def _request(self, method: str, path: str, data: dict | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        # Critical: serialize empty dict {} as b"{}" instead of dropping to None to satisfy FastAPI schemas
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                err_content = exc.read().decode("utf-8", errors="replace")
                return {"error": f"HTTP {exc.code}: {err_content}"}
            except Exception:
                return {"error": str(exc)}
        except Exception as exc:
            logger.warning("Honcho API call failed: %s %s -> %s", method, path, exc)
            return {"error": str(exc)}

    def health(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/health", headers=self._headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("status") == "ok"
        except Exception:
            return False

    def _ws(self) -> str:
        return f"/v3/workspaces/{self.workspace}"

    # --- Peers ---

    def create_peer(self, peer_id: str, metadata: dict | None = None) -> dict:
        return self._request("POST", f"{self._ws()}/peers", {
            "id": peer_id,
            "metadata": metadata or {},
        })

    def get_peer(self, peer_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/peers/{peer_id}")

    def get_peer_representation(self, peer_id: str, search_query: str = "") -> dict:
        body = {}
        if search_query:
            body["search_query"] = search_query
        return self._request("POST", f"{self._ws()}/peers/{peer_id}/representation", body)

    def get_peer_card(self, peer_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/peers/{peer_id}/card")

    def get_peer_context(self, peer_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/peers/{peer_id}/context")

    def peer_chat(self, peer_id: str, message: str) -> dict:
        return self._request("POST", f"{self._ws()}/peers/{peer_id}/chat", {
            "message": message,
        })

    # --- Sessions ---

    def create_session(self, session_id: str, peers: dict | None = None) -> dict:
        return self._request("POST", f"{self._ws()}/sessions", {
            "id": session_id,
            "peers": peers or {},
        })

    def list_sessions(self) -> dict:
        return self._request("POST", f"{self._ws()}/sessions/list", {})

    def get_session(self, session_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/sessions/{session_id}")

    def get_session_context(self, session_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/sessions/{session_id}/context")

    def get_session_summaries(self, session_id: str) -> dict:
        return self._request("GET", f"{self._ws()}/sessions/{session_id}/summaries")

    # --- Messages ---

    def add_message(self, session_id: str, peer_id: str, content: str) -> dict:
        return self._request("POST", f"{self._ws()}/sessions/{session_id}/messages", {
            "messages": [{"peer_id": peer_id, "content": content}],
        })

    def list_messages(self, session_id: str) -> dict:
        return self._request("POST", f"{self._ws()}/sessions/{session_id}/messages/list", {})

    # --- Search ---

    def search(self, query: str, session_id: str = "") -> dict:
        if session_id:
            return self._request("POST", f"{self._ws()}/sessions/{session_id}/search", {"query": query})
        return self._request("POST", f"{self._ws()}/search", {"query": query})

    # --- Conclusions ---

    def get_conclusions(self, peer_id: str = "") -> dict:
        return self._request("POST", f"{self._ws()}/conclusions/list", {"peer_id": peer_id} if peer_id else {})

    def query_conclusions(self, query: str) -> dict:
        return self._request("POST", f"{self._ws()}/conclusions/query", {"query": query})
