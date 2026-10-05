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


def test_browser_url_stays_on_loopback_when_tailscale_is_up(monkeypatch):
    ui = make_service(monkeypatch)
    monkeypatch.setattr(service, "_tailscale_ipv4", lambda: "100.74.2.15")
    assert ui.browser_url() == "http://127.0.0.1:9790/"


def test_urls_expose_only_adapter_and_webui(monkeypatch):
    urls = make_service(monkeypatch).urls()
    assert urls.adapter == "http://127.0.0.1:9791/"
    assert urls.web_ui == "http://127.0.0.1:9790/"
    assert set(urls.__dataclass_fields__) == {"adapter", "web_ui"}


def test_serve_url_is_advertised_only_when_publishing(monkeypatch):
    ui = make_service(monkeypatch)
    monkeypatch.setattr(service, "_tailscale_dns_name", lambda: "mac.example.ts.net")
    assert ui.serve_url() is None  # publishing off
    ui.tailscale_publish = True
    assert ui.serve_url() == "https://mac.example.ts.net:8443/"
    assert ui.browser_url() == "http://127.0.0.1:9790/"  # local opens stay on loopback
    ui.tailscale_https_port = 443
    assert ui.serve_url() == "https://mac.example.ts.net/"
    monkeypatch.setattr(service, "_tailscale_dns_name", lambda: None)
    assert ui.serve_url() is None


def test_smoke_script_targets_loopback_and_serve_not_raw_tailnet_ip(monkeypatch):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "scripts" / "verify-stack-smoke.py"
    text = path.read_text(encoding="utf-8")
    assert "100.74." not in text
    spec = importlib.util.spec_from_file_location("verify_stack_smoke", path)
    module = importlib.util.module_from_spec(spec)
    import sys
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert module.resolve_chat_url(None) == "http://127.0.0.1:8790/"
    assert module.resolve_chat_url("https://mac.example.ts.net:8443") == "https://mac.example.ts.net:8443/"
