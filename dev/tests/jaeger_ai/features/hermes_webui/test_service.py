"""Focused tests for Hermes WebUI settings toggle + feature service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from jaeger_ai.core.instance.schemas import ContainersConfig, WebhookConfig
from jaeger_ai.features.hermes_webui.service import (
    HermesWebUIService,
    hermes_webui_urls,
)


def test_containers_use_hermes_webui_is_catalogued():
    field = ContainersConfig.model_fields["use_hermes_webui"]
    extra = field.json_schema_extra or {}
    assert extra.get("group") == "containers"
    assert ContainersConfig().use_hermes_webui is False
    assert ContainersConfig().hermes_webui_container == "hermes-webui-hermes-webui"
    assert ContainersConfig().hermes_webui_port == 8787
    assert ContainersConfig().adapter_port == 8791


def test_webhook_default_no_longer_collides_with_adapter():
    assert WebhookConfig().port == 8793
    assert ContainersConfig().adapter_port == 8791


def test_hermes_webui_urls():
    urls = hermes_webui_urls(webui_port=8787, adapter_port=8791)
    assert urls.container_ui == "http://127.0.0.1:8787/"
    assert urls.adapter == "http://127.0.0.1:8791/"
    assert urls.vendor_ui == "http://127.0.0.1:8790/"


def test_start_requires_toggle_unless_forced(tmp_path, monkeypatch):
    layout = MagicMock()
    layout.root = tmp_path
    layout.exists.return_value = True
    cfg = MagicMock()
    cfg.containers = ContainersConfig(use_hermes_webui=False)

    with patch(
        "jaeger_ai.features.hermes_webui.service._load_containers_config",
        return_value={
            "use_hermes_webui": False,
            "hermes_webui_container": "hermes-webui-hermes-webui",
            "hermes_webui_port": 8787,
            "adapter_port": 8791,
            "layout": layout,
            "instance": "jaeger",
        },
    ):
        svc = HermesWebUIService("jaeger")
        denied = svc.start()
        assert denied["ok"] is False
        assert "use_hermes_webui" in denied["error"]

        with patch(
            "jaeger_ai.features.hermes_webui.service.cs.start_container",
            return_value={"ok": True, "id": "hermes-webui-hermes-webui"},
        ) as start_ctn, patch.object(
            HermesWebUIService, "_start_adapter", return_value={"ok": True, "pid": 1}
        ), patch.object(
            HermesWebUIService,
            "status",
            return_value={
                "container": {"url": "http://127.0.0.1:8787/"},
                "adapter": {},
            },
        ):
            allowed = svc.start(force=True)
            assert allowed["ok"] is True
            start_ctn.assert_called_once_with("hermes-webui-hermes-webui")


def test_webui_dispatch_registered():
    from jaeger_ai.cli.verbs.dispatch import SUBCOMMANDS

    assert "webui" in SUBCOMMANDS
