"""Home Assistant plugin — unconfigured error shape, URL building,
service-call payload shape (HTTP layer mocked), and tool registration.
No live HA instance is ever contacted."""

from __future__ import annotations

import pytest

from jaeger_os.core.safety.permissions import (
    AllowAllProvider,
    PermissionPolicy,
    use_policy,
)
from jaeger_os.plugins import homeassistant as ha


@pytest.fixture(autouse=True)
def _no_instance_config(monkeypatch):
    """Isolate from the developer's real env + credential store: no
    layout, no HASS_* env vars unless a test sets them."""
    monkeypatch.setattr(ha, "_layout_or_none", lambda: None)
    monkeypatch.delenv("HASS_URL", raising=False)
    monkeypatch.delenv("HASS_TOKEN", raising=False)


def _allow():
    return use_policy(PermissionPolicy(confirmation=AllowAllProvider()))


# ── unconfigured → friendly setup error, never a crash ──────────────


def test_unconfigured_returns_setup_error_not_crash() -> None:
    res = ha.ha_get_state(entity_id="light.living_room")
    assert res["ok"] is False
    assert "HASS_TOKEN" in res["error"]
    assert "set_credential" in res["error"]
    # And the same shape from the list tools.
    assert ha.ha_list_entities()["ok"] is False
    assert ha.ha_list_services()["ok"] is False


def test_unconfigured_call_service_errors_before_any_http(monkeypatch) -> None:
    def _boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("HTTP layer must not be reached when unconfigured")
    monkeypatch.setattr(ha, "_api_post", _boom)
    with _allow():
        res = ha.ha_call_service(domain="light", service="turn_on",
                                 entity_id="light.kitchen")
    assert res["ok"] is False
    assert "HASS_TOKEN" in res["error"]


# ── URL building / config resolution ────────────────────────────────


def test_config_defaults_and_trailing_slash_stripped(monkeypatch) -> None:
    monkeypatch.setenv("HASS_TOKEN", "tok123")
    url, token = ha._get_config()
    assert url == "http://homeassistant.local:8123"  # default URL
    assert token == "tok123"
    monkeypatch.setenv("HASS_URL", "http://10.0.0.5:8123/")
    url, _ = ha._get_config()
    assert url == "http://10.0.0.5:8123"  # rstrip'd — no double slash in paths


# ── service-call payload shape (HTTP mocked) ────────────────────────


def test_call_service_posts_correct_path_and_payload(monkeypatch) -> None:
    monkeypatch.setenv("HASS_TOKEN", "tok123")
    monkeypatch.setenv("HASS_URL", "http://ha.local:8123")
    seen: dict = {}

    def fake_post(path, payload, base_url, token):
        seen.update(path=path, payload=payload, base_url=base_url, token=token)
        return [{"entity_id": "light.kitchen", "state": "on"}]

    monkeypatch.setattr(ha, "_api_post", fake_post)
    with _allow():
        res = ha.ha_call_service(domain="light", service="turn_on",
                                 entity_id="light.kitchen",
                                 data_json='{"brightness": 128, "entity_id": "light.wrong"}')
    assert seen["path"] == "/api/services/light/turn_on"
    assert seen["base_url"] == "http://ha.local:8123"
    assert seen["token"] == "tok123"
    # entity_id argument wins over data_json's entity_id (Hermes parity).
    assert seen["payload"] == {"brightness": 128, "entity_id": "light.kitchen"}
    assert res == {"ok": True, "service": "light.turn_on",
                   "affected_entities": [{"entity_id": "light.kitchen",
                                          "state": "on"}]}


def test_call_service_validation_blocks_bad_input_before_http(monkeypatch) -> None:
    monkeypatch.setenv("HASS_TOKEN", "tok123")

    def _boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("HTTP layer must not be reached on invalid input")
    monkeypatch.setattr(ha, "_api_post", _boom)

    with _allow():
        # Blocked-for-security domain.
        blocked = ha.ha_call_service(domain="shell_command", service="run")
        # Path-traversal shaped names.
        traversal = ha.ha_call_service(domain="shell_command/../light",
                                       service="turn_on")
        bad_entity = ha.ha_call_service(domain="light", service="turn_on",
                                        entity_id="not-an-entity")
        bad_json = ha.ha_call_service(domain="light", service="turn_on",
                                      entity_id="light.kitchen",
                                      data_json="{nope")
    for res in (blocked, traversal, bad_entity, bad_json):
        assert res["ok"] is False
    assert "blocked" in blocked["error"]
    assert "invalid domain" in traversal["error"]


def test_list_entities_filters_domain_and_area(monkeypatch) -> None:
    monkeypatch.setenv("HASS_TOKEN", "tok123")
    states = [
        {"entity_id": "light.kitchen", "state": "on",
         "attributes": {"friendly_name": "Kitchen Light"}},
        {"entity_id": "light.bedroom", "state": "off",
         "attributes": {"friendly_name": "Bedroom Lamp"}},
        {"entity_id": "sensor.kitchen_temp", "state": "21.5",
         "attributes": {"friendly_name": "Kitchen Temperature"}},
    ]
    monkeypatch.setattr(ha, "_api_get", lambda path, base_url, token: states)
    res = ha.ha_list_entities(domain="light", area="kitchen")
    assert res["ok"] is True
    assert res["count"] == 1
    assert res["entities"] == [{"entity_id": "light.kitchen", "state": "on",
                                "friendly_name": "Kitchen Light"}]


# ── registration ─────────────────────────────────────────────────────


def test_tools_registered_and_register_ctx_exposes_them() -> None:
    from jaeger_os.agent.schemas.tool_registry import get_tool, has_tool
    from jaeger_os.plugins.registry import PluginContext

    for name in ha.TOOL_NAMES:
        assert has_tool(name), f"{name} not in the tool registry"
        # Docstring became the model-facing description.
        assert get_tool(name).description.strip()

    ctx = PluginContext()
    ha.register(ctx)
    assert [t.name for t in ctx.tools] == list(ha.TOOL_NAMES)
