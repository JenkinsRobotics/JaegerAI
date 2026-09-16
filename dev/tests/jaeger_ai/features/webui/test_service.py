"""Focused tests for Jaeger's first-party WebUI service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from jaeger_ai.core.instance.schemas import ContainersConfig, WebhookConfig
from jaeger_ai.features.webui.service.service import WebUIService, webui_urls


def _config(layout, **changes):
    config = {
        "adapter_port": 8791,
        "jaeger_webui_port": 8790,
        "tailscale_publish": False,
        "tailscale_https_port": 8443,
        "layout": layout,
        "instance": "jaeger",
    }
    config.update(changes)
    return config


def test_webui_settings_are_catalogued():
    cfg = ContainersConfig()
    assert cfg.adapter_port == 8791
    assert cfg.jaeger_webui_port == 8790
    assert cfg.tailscale_publish is False
    assert cfg.tailscale_https_port == 8443
    assert "use_hermes_webui" not in ContainersConfig.model_fields
    assert "hermes_webui_container" not in ContainersConfig.model_fields
    assert "hermes_webui_port" not in ContainersConfig.model_fields


def test_webhook_default_no_longer_collides_with_adapter():
    assert WebhookConfig().port == 8793
    assert ContainersConfig().adapter_port == 8791


def test_webui_urls():
    urls = webui_urls(webui_port=8787, adapter_port=8791)
    assert urls.adapter == "http://127.0.0.1:8791/"
    assert urls.web_ui == "http://127.0.0.1:8787/"


def test_webui_dispatch_registered():
    from jaeger_ai.cli.verbs.dispatch import SUBCOMMANDS

    assert "webui" in SUBCOMMANDS


def test_start_runs_adapter_then_webui_and_can_publish(tmp_path):
    layout = MagicMock()
    layout.root = tmp_path
    calls = []
    with patch(
        "jaeger_ai.features.webui.service.service._load_webui_config",
        return_value=_config(layout),
    ), patch(
        "jaeger_ai.features.webui.service.service.prepare_webui_home", return_value={}
    ):
        svc = WebUIService("jaeger")
        with patch.object(
            svc, "_start_adapter", side_effect=lambda: calls.append("adapter") or {"ok": True}
        ), patch.object(
            svc, "_start_webui", side_effect=lambda: calls.append("webui") or {"ok": True}
        ), patch.object(
            svc, "publish_tailscale", return_value={"ok": True, "output": "https://jaeger.tailnet/"}
        ) as publish:
            result = svc.start(publish_tailscale=True)
    assert result["ok"] is True
    assert result["open"] == "http://127.0.0.1:8790/"
    assert calls == ["adapter", "webui"]
    publish.assert_called_once_with()


def test_webui_status_treats_listener_as_running(tmp_path):
    layout = MagicMock()
    layout.root = tmp_path
    with patch(
        "jaeger_ai.features.webui.service.service._load_webui_config",
        return_value=_config(layout),
    ):
        svc = WebUIService("jaeger")
        with patch(
            "jaeger_ai.features.webui.service.service._listening_pid", return_value=78503
        ):
            status = svc._webui_status()
    assert status["running"] is True
    assert status["pid"] == 78503
    assert status["source"] == "listener"


def test_stop_webui_reaps_listener_when_pid_file_is_missing(tmp_path):
    layout = MagicMock()
    layout.root = tmp_path
    with patch(
        "jaeger_ai.features.webui.service.service._load_webui_config",
        return_value=_config(layout),
    ):
        svc = WebUIService("jaeger")
        with patch.object(
            svc, "_webui_status", return_value={"running": True, "pid": 78503, "source": "listener"}
        ), patch(
            "jaeger_ai.features.webui.service.service._pid_alive", side_effect=[True, False, False]
        ), patch(
            "jaeger_ai.features.webui.service.service.os.kill"
        ) as kill:
            result = svc._stop_webui()
    assert result["ok"] is True
    kill.assert_called_once()


def test_tailscale_publishes_only_webui(tmp_path):
    layout = MagicMock()
    layout.root = tmp_path
    with patch(
        "jaeger_ai.features.webui.service.service._load_webui_config",
        return_value=_config(layout),
    ), patch(
        "jaeger_ai.features.webui.service.service.shutil.which",
        return_value="/usr/bin/tailscale",
    ), patch(
        "jaeger_ai.features.webui.service.service.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="https://jaeger.tailnet/", stderr=""),
    ) as run:
        result = WebUIService("jaeger").publish_tailscale()
    assert result["ok"] is True
    run.assert_called_once_with(
        ["/usr/bin/tailscale", "serve", "--bg", "--https=8443", "http://127.0.0.1:8790"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
