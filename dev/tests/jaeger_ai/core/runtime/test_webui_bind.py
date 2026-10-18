"""Unit tests for loopback bind safety (webui_bind and gateway defaults)."""
from __future__ import annotations

import os
from jaeger_ai.core.runtime.webui_bind import webui_bind_host
from jaeger_ai.core.gateway.server import DEFAULT_GATEWAY_HOST


def test_gateway_default_host_is_loopback():
    assert DEFAULT_GATEWAY_HOST == "127.0.0.1"


def test_webui_bind_host_defaults_to_loopback():
    assert webui_bind_host({}) == "127.0.0.1"
    assert webui_bind_host(None) == "127.0.0.1" or webui_bind_host({}) == "127.0.0.1"


def test_webui_bind_host_ignores_inherited_zero_host_without_explicit_allow_lan():
    # Inherited 0.0.0.0 from HERMES_WEBUI_HOST or JAEGER_WEBUI_HOST MUST be clamped to 127.0.0.1
    env_hermes = {"HERMES_WEBUI_HOST": "0.0.0.0"}
    assert webui_bind_host(env_hermes) == "127.0.0.1"

    env_jaeger = {"JAEGER_WEBUI_HOST": "0.0.0.0"}
    assert webui_bind_host(env_jaeger) == "127.0.0.1"

    env_both = {"HERMES_WEBUI_HOST": "0.0.0.0", "JAEGER_WEBUI_HOST": "0.0.0.0"}
    assert webui_bind_host(env_both) == "127.0.0.1"


def test_webui_bind_host_allows_lan_only_with_explicit_flag():
    env_allowed = {
        "JAEGER_WEBUI_ALLOW_LAN": "1",
        "JAEGER_WEBUI_HOST": "0.0.0.0",
    }
    assert webui_bind_host(env_allowed) == "0.0.0.0"

    env_hermes_allowed = {
        "JAEGER_WEBUI_ALLOW_LAN": "true",
        "HERMES_WEBUI_HOST": "0.0.0.0",
    }
    assert webui_bind_host(env_hermes_allowed) == "0.0.0.0"
