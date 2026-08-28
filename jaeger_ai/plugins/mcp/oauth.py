"""OAuth for MCP servers — token storage plus a per-server provider manager.

Ported from hermes-agent ``tools/mcp_oauth.py`` / ``tools/mcp_oauth_manager.py``.
hermes-agent is MIT licensed:

    Copyright (c) 2025 Nous Research

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial
    portions of the Software.

Before this, Jaeger's MCP support handled credential-ref indirection and
inline-secret migration well but had no OAuth flow at all, so any MCP server
that authenticates with OAuth was simply unreachable.

The manager is the single place that constructs the SDK's
``OAuthClientProvider``, and it carries the two behaviours the donor found
were needed in practice — both of which are about *other* processes and
*concurrent* calls, so neither shows up until real use:

**Cross-process token reload.** When something else refreshes the tokens on
disk (a cron job, a second Jaeger, the operator running a login), an
in-memory provider would keep presenting the stale access token until
restart. The store is watched by mtime and reloaded when it changes. The
donor cites the same bug class in Claude Code's
``invalidateOAuthCacheIfDiskChanged`` and Codex's ``refresh_oauth_if_needed``.

**401 de-duplication.** When N concurrent tool calls hit 401 on the same
expired token, exactly one recovery runs and the rest await its result.
Without this, N refreshes race and all but one of the resulting tokens is
immediately discarded — and some providers rotate refresh tokens, so the
losers can invalidate the winner.

ADAPTATIONS. Tokens live under ``<instance>/credentials/mcp-oauth/`` rather
than a user-global directory, so two Jaeger instances hold separate grants —
consistent with how the rest of instance state is scoped, and it means
deleting an instance revokes nothing it did not own. File modes are 0600.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CLIENT_NAME = "JaegerAI"
_CALLBACK_TIMEOUT = 300.0


def _safe_name(server: str) -> str:
    """Filesystem-safe per-server key.

    A server name comes from config, so it must never escape the token
    directory. Separators are replaced, which already defeats traversal —
    ``../../x`` becomes ``.._.._x``, a plain filename. The extra guard is for
    the degenerate names that are dangerous *without* a separator: ``.`` and
    ``..`` name directories, so a purely-dot result is replaced outright.
    """
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_"
                      for c in (server or "unknown"))[:80]
    if not cleaned.strip(".") or not cleaned:
        return "unnamed"
    return cleaned


def token_dir(layout: Any = None) -> Path:
    if layout is None:
        from jaeger_agent.workspace import get_layout
        layout = get_layout()
    return Path(layout.credentials_dir) / "mcp-oauth"


class FileTokenStorage:
    """``mcp.client.auth.TokenStorage`` backed by a 0600 JSON file per server.

    Implements the SDK's async protocol. Reads are mtime-guarded so a refresh
    written by another process is picked up on the next access rather than
    after a restart.
    """

    def __init__(self, server: str, layout: Any = None) -> None:
        self.server = server
        self._path = token_dir(layout) / f"{_safe_name(server)}.json"
        self._client_path = token_dir(layout) / f"{_safe_name(server)}.client.json"
        self._stamp: tuple[float, int] | None = None
        self._cached: Any = None

    # ── internals ───────────────────────────────────────────────────

    @staticmethod
    def _stat(path: Path) -> tuple[float, int] | None:
        try:
            st = path.stat()
            return (st.st_mtime, st.st_size)
        except OSError:
            return None

    def _write(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _read(path: Path) -> dict | None:
        try:
            if not path.is_file():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def disk_changed(self) -> bool:
        """True when the token file changed since we last read it."""
        return self._stat(self._path) != self._stamp

    # ── TokenStorage protocol ───────────────────────────────────────

    async def get_tokens(self) -> Any:
        from mcp.shared.auth import OAuthToken

        stamp = self._stat(self._path)
        if self._cached is not None and stamp == self._stamp:
            return self._cached
        raw = self._read(self._path)
        self._stamp = stamp
        if not raw:
            self._cached = None
            return None
        try:
            self._cached = OAuthToken.model_validate(raw)
        except Exception as exc:
            logger.warning("mcp oauth: stored token for %r is unreadable (%s)",
                           self.server, exc)
            self._cached = None
        return self._cached

    async def set_tokens(self, tokens: Any) -> None:
        self._write(self._path, tokens.model_dump(mode="json", exclude_none=True))
        self._stamp = self._stat(self._path)
        self._cached = tokens

    async def get_client_info(self) -> Any:
        from mcp.shared.auth import OAuthClientInformationFull

        raw = self._read(self._client_path)
        if not raw:
            return None
        try:
            return OAuthClientInformationFull.model_validate(raw)
        except Exception:
            return None

    async def set_client_info(self, info: Any) -> None:
        self._write(self._client_path,
                    info.model_dump(mode="json", exclude_none=True))


class OAuthManager:
    """One provider per server, plus 401 de-duplication.

    Deliberately process-wide: two providers for one server would each hold
    their own in-memory token and race each other's refreshes.
    """

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._storages: dict[str, FileTokenStorage] = {}
        self._lock = threading.Lock()
        self._inflight: dict[str, asyncio.Future] = {}

    # ── providers ───────────────────────────────────────────────────

    def provider(self, server: str, url: str, *, scope: str = "",
                 layout: Any = None) -> Any:
        """The ``OAuthClientProvider`` for *server*, constructed once.

        Rebuilt when the token file changed underneath us, which is how a
        refresh performed by another process reaches this one.
        """
        with self._lock:
            storage = self._storages.get(server)
            if storage is not None and storage.disk_changed():
                logger.info("mcp oauth: tokens for %r changed on disk — "
                            "rebuilding provider", server)
                self._providers.pop(server, None)
            existing = self._providers.get(server)
            if existing is not None:
                return existing

        from mcp.client.auth import OAuthClientProvider
        from mcp.shared.auth import OAuthClientMetadata

        storage = FileTokenStorage(server, layout)
        metadata = OAuthClientMetadata(
            client_name=_DEFAULT_CLIENT_NAME,
            redirect_uris=["http://localhost:8765/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=scope or None,
        )
        provider = OAuthClientProvider(
            server_url=url,
            client_metadata=metadata,
            storage=storage,
            redirect_handler=_redirect_handler,
            callback_handler=_callback_handler,
            timeout=_CALLBACK_TIMEOUT,
        )
        with self._lock:
            self._providers[server] = provider
            self._storages[server] = storage
        return provider

    def forget(self, server: str) -> None:
        with self._lock:
            self._providers.pop(server, None)
            self._storages.pop(server, None)

    def reset(self) -> None:
        with self._lock:
            self._providers.clear()
            self._storages.clear()
            self._inflight.clear()

    # ── 401 de-duplication ──────────────────────────────────────────

    async def recover_once(self, server: str, recover) -> Any:
        """Run *recover* once per server even if N callers race here.

        The first caller creates the future and runs the recovery; the rest
        await the same future. Concurrent refreshes are not merely wasteful —
        providers that rotate refresh tokens will invalidate the winner's
        token when the losers' refreshes land.
        """
        loop = asyncio.get_running_loop()
        with self._lock:
            pending = self._inflight.get(server)
            if pending is not None and not pending.done():
                fut = pending
                leader = False
            else:
                fut = loop.create_future()
                self._inflight[server] = fut
                leader = True

        if not leader:
            return await fut

        try:
            result = await recover()
        except Exception as exc:
            if not fut.done():
                fut.set_exception(exc)
            raise
        else:
            if not fut.done():
                fut.set_result(result)
            return result
        finally:
            with self._lock:
                if self._inflight.get(server) is fut:
                    self._inflight.pop(server, None)


async def _redirect_handler(authorization_url: str) -> None:
    """Show the operator the URL to visit.

    Printed rather than auto-opened: this can fire from the headless daemon,
    where silently launching a browser on someone's desktop would be a
    surprise, and where there may be no desktop at all.
    """
    print("\n[mcp-oauth] authorize this MCP server by visiting:\n"
          f"  {authorization_url}\n", flush=True)


async def _callback_handler() -> tuple[str, str | None]:
    """Collect the authorization code pasted back by the operator."""
    loop = asyncio.get_running_loop()
    code = await loop.run_in_executor(
        None, lambda: input("[mcp-oauth] paste the ?code= value: ").strip())
    return code, None


_manager: OAuthManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> OAuthManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = OAuthManager()
        return _manager


def reset_manager() -> None:
    """Test seam."""
    global _manager
    with _manager_lock:
        _manager = None


def server_uses_oauth(config: Any) -> bool:
    """Whether a configured server asked for OAuth."""
    auth = str(getattr(config, "auth", "") or "").strip().lower()
    return auth in ("oauth", "oauth2")


__all__ = [
    "FileTokenStorage", "OAuthManager", "get_manager", "reset_manager",
    "server_uses_oauth", "token_dir",
]
