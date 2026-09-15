from __future__ import annotations

import asyncio
import json

import pytest

from integrations.hermes_webui.native_adapter import native_adapter_class


class _UpstreamAdapter:
    def _create_agent(self, session_id=None, **kwargs):
        return object()

    def _http_route_table(self):
        return [
            ("GET", "/health", object()),
            ("POST", "/v1/runs", object()),
            ("GET", "/v1/runs/{run_id}", object()),
            ("GET", "/v1/runs/{run_id}/events", object()),
            ("GET", "/api/sessions/{session_id}/messages", object()),
        ]


def test_native_adapter_adds_semver_version_without_replacing_upstream_routes(monkeypatch):
    monkeypatch.setattr(
        "integrations.hermes_webui.native_adapter._component_version",
        lambda: "0.20.5",
    )
    adapter = native_adapter_class(_UpstreamAdapter)()
    routes = adapter._http_route_table()
    assert [(method, path) for method, path, _handler in routes[:-1]] == [
        (method, path) for method, path, _handler in _UpstreamAdapter()._http_route_table()
    ]
    assert routes[-1][:2] == ("GET", "/version")
    response = asyncio.run(routes[-1][2](None))
    assert response.status == 200
    assert json.loads(response.body) == {
        "component": "hermes-runs",
        "version": "0.20.5",
        "protocol_version": "1",
    }


def test_native_adapter_rejects_an_incompatible_upstream_route_table():
    class MissingRuns(_UpstreamAdapter):
        def _http_route_table(self):
            return [("GET", "/health", object())]

    adapter = native_adapter_class(MissingRuns)()
    with pytest.raises(RuntimeError, match="required native API routes"):
        adapter._http_route_table()


def test_native_adapter_rejects_an_incompatible_agent_factory():
    class MissingSessionContract(_UpstreamAdapter):
        def _create_agent(self):
            return object()

    with pytest.raises(RuntimeError, match="_create_agent session contract"):
        native_adapter_class(MissingSessionContract)
