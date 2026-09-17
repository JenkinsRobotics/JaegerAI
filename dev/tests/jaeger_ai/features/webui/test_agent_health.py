from __future__ import annotations

from jaeger_ai.features.webui.api import agent_health


def test_remote_gateway_http_503_is_alive_but_degraded(monkeypatch):
    responses = iter(
        [
            (False, 404, "HTTPError", None),
            (False, 503, "HTTPError", None),
            (False, 404, "HTTPError", None),
            (False, 404, "HTTPError", None),
        ]
    )
    monkeypatch.setattr(agent_health, "_http_probe", lambda *args, **kwargs: next(responses))

    payload = agent_health._run_remote_probe("http://127.0.0.1:8810")

    assert payload["alive"] is True
    assert payload["details"] == {
        "state": "degraded",
        "reason": "remote_gateway_http_response",
        "endpoint": "http://127.0.0.1:8810/health/detailed",
        "status_code": 404,
    }


def test_remote_gateway_transport_failure_is_down(monkeypatch):
    monkeypatch.setattr(
        agent_health,
        "_http_probe",
        lambda *args, **kwargs: (False, None, "URLError", None),
    )

    payload = agent_health._run_remote_probe("http://127.0.0.1:8810")

    assert payload["alive"] is False
    assert payload["details"]["reason"] == "remote_gateway_unreachable"
    assert payload["details"]["error"] == "URLError"
