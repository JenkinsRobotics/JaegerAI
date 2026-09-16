"""Construction-time contract for Jaeger's stock Hermes Runs sidecar.

The adapter subclasses the documented route-table seam only. It does not
replace agent methods. A composition proxy supplies structured SessionDB history
until the upstream Runs endpoint owns that behavior.
"""
from __future__ import annotations

import inspect
import re
import uuid

from aiohttp import web

_SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")
_REQUIRED_ROUTES = {
    ("GET", "/health"),
    ("POST", "/v1/runs"),
    ("GET", "/v1/runs/{run_id}"),
    ("GET", "/v1/runs/{run_id}/events"),
    ("GET", "/api/sessions/{session_id}/messages"),
}


def _component_version() -> str:
    try:
        from gateway.platforms.api_server import _hermes_version

        version = str(_hermes_version() or "").removeprefix("v")
    except (ImportError, AttributeError):
        version = ""
    if not _SEMVER.fullmatch(version):
        raise RuntimeError("Hermes Runs version is unavailable or is not semantic versioning")
    return version


def native_adapter_class(upstream):
    """Return the narrow Jaeger adapter after checking the upstream protocol."""

    create_agent = getattr(upstream, "_create_agent", None)
    route_table = getattr(upstream, "_http_route_table", None)
    if not callable(create_agent) or "session_id" not in inspect.signature(create_agent).parameters:
        raise RuntimeError("Hermes changed the _create_agent session contract")
    if not callable(route_table):
        raise RuntimeError(  # noqa: TRY004 - an upstream contract violation
            "Hermes removed the native API route-table contract"
        )

    class HistoryAgentProxy:
        """Add native SessionDB history without modifying the Hermes agent."""

        def __init__(self, agent, database, session_id):
            object.__setattr__(self, "_agent", agent)
            object.__setattr__(self, "_database", database)
            object.__setattr__(self, "_session_id", session_id)

        def __getattr__(self, name):
            return getattr(self._agent, name)

        def __setattr__(self, name, value):
            setattr(self._agent, name, value)

        def run_conversation(self, *args, **kwargs):
            if self._session_id and not kwargs.get("conversation_history"):
                kwargs["conversation_history"] = self._database.get_messages_as_conversation(
                    self._session_id
                )
            return self._agent.run_conversation(*args, **kwargs)

    class JaegerNativeAdapter(upstream):
        def _http_route_table(self):
            routes = list(super()._http_route_table())
            available = {(str(method).upper(), path) for method, path, _handler in routes}
            missing = sorted(_REQUIRED_ROUTES - available)
            if missing:
                raise RuntimeError(
                    "Hermes changed required native API routes: "
                    + ", ".join(f"{method} {path}" for method, path in missing)
                )
            if ("GET", "/version") in available:
                raise RuntimeError("Hermes now owns GET /version; remove the Jaeger adapter route")
            routes.append(("GET", "/version", self._handle_jaeger_version))
            return routes

        def _create_agent(self, *args, **kwargs):
            session_id = kwargs.get("session_id")
            database = self._ensure_session_db() if session_id else None
            if session_id and database is None:
                raise RuntimeError(
                    "Native session database unavailable; refusing a contextless turn"
                )
            if database is not None:
                if re.fullmatch(r"roundtable-hermes:[0-9a-f]{32}", session_id):
                    member_id = session_id.split(":", 1)[1]
                    legacy_id = uuid.uuid5(
                        uuid.NAMESPACE_URL, f"jaeger-roundtable:{member_id}:hermes"
                    ).hex
                    legacy = database.resolve_session_by_title(
                        f"Roundtable {legacy_id[:12]} — Hermes"
                    )
                    session_id = legacy or session_id
                session_id = database.resolve_resume_session_id(session_id) or session_id
                kwargs["session_id"] = session_id
            agent = super()._create_agent(*args, **kwargs)
            return HistoryAgentProxy(agent, database, session_id) if database is not None else agent

        async def _handle_jaeger_version(self, request):
            return web.json_response({
                "component": "hermes-runs",
                "version": _component_version(),
                "protocol_version": "1",
            })

    JaegerNativeAdapter.__name__ = "JaegerNativeAdapter"
    return JaegerNativeAdapter


__all__ = ["native_adapter_class"]
