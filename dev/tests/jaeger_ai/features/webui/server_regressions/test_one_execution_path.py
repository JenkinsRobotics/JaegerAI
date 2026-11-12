"""The WebUI has one execution path: the Gateway. Every other path is isolated."""

from types import SimpleNamespace

import pytest
from api import gateway_chat, routes

ENV = "JAEGER_LEGACY_PATHS"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (ENV, "HERMES_WEBUI_CHAT_BACKEND", "JAEGER_GATEWAY_URL", "HERMES_WEBUI_GATEWAY_URL"):
        monkeypatch.delenv(name, raising=False)


def test_default_backend_is_the_gateway():
    assert gateway_chat.webui_chat_backend_mode({}, {}) == "gateway"
    assert gateway_chat.webui_gateway_chat_enabled({}, {}) is True


def test_in_process_backend_needs_the_explicit_switch():
    assert gateway_chat.webui_chat_backend_mode({}, {ENV: "1"}) == "legacy"
    # An explicit gateway selection still wins over the switch.
    assert gateway_chat.webui_chat_backend_mode(
        {}, {ENV: "1", "JAEGER_GATEWAY_URL": "http://127.0.0.1:33418"}
    ) == "gateway"

