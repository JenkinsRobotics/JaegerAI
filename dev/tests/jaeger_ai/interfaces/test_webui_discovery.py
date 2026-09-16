"""Discovery advertises the single first-party Jaeger WebUI."""

from jaeger_ai.features.webui.service import service


def make_service(monkeypatch):
    config = dict(
        instance="selected",
        layout=None,
        adapter_port=9791,
        jaeger_webui_port=9790,
        tailscale_publish=False,
        tailscale_https_port=8443,
    )
    monkeypatch.setattr(service, "_load_webui_config", lambda instance: config)
    monkeypatch.setattr(service, "_tailscale_ipv4", lambda: None)
    return service.WebUIService("selected")


def test_browser_url_uses_configured_webui_port(monkeypatch):
    assert make_service(monkeypatch).browser_url() == "http://127.0.0.1:9790/"


def test_browser_url_prefers_tailscale_webui_port(monkeypatch):
    ui = make_service(monkeypatch)
    monkeypatch.setattr(service, "_tailscale_ipv4", lambda: "100.74.2.15")
    assert ui.browser_url() == "http://100.74.2.15:9790/"


def test_urls_expose_only_adapter_and_webui(monkeypatch):
    urls = make_service(monkeypatch).urls()
    assert urls.adapter == "http://127.0.0.1:9791/"
    assert urls.web_ui == "http://127.0.0.1:9790/"
    assert set(urls.__dataclass_fields__) == {"adapter", "web_ui"}
