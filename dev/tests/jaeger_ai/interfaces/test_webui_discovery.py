"""Discovery must advertise Jaeger WebUI :8790, not the Hermes runtime container."""
import json
import subprocess

from jaeger_ai.features.hermes_webui import service


def make_service(monkeypatch, **changes):
    config = dict(instance='selected', layout=None, use_hermes_webui=True,
                  engine='/custom/container', hermes_webui_container='custom-ui',
                  hermes_webui_port=9887, adapter_port=9791, jaeger_webui_port=9790)
    config.update(changes)
    monkeypatch.setattr(service, '_load_containers_config', lambda instance: config)
    monkeypatch.setattr(service, '_tailscale_ipv4', lambda: None)
    monkeypatch.setattr(
        "jaeger_ai.core.runtime.agent_workspaces.container_name",
        lambda role: config["hermes_webui_container"],
    )
    monkeypatch.delenv('CONTAINER_CLI', raising=False)
    return service.HermesWebUIService('selected')


def test_browser_url_is_vendor_even_when_container_toggle_is_on(monkeypatch):
    ui = make_service(monkeypatch)
    def unexpected(*args, **kwargs):
        raise AssertionError('Chat URL must not inspect the Hermes container')
    monkeypatch.setattr(service.subprocess, 'run', unexpected)
    assert ui.browser_url() == 'http://127.0.0.1:9790/'


def test_browser_url_prefers_tailscale_vendor_port(monkeypatch):
    ui = make_service(monkeypatch)
    monkeypatch.setattr(service, '_tailscale_ipv4', lambda: '100.74.2.15')
    assert ui.browser_url() == 'http://100.74.2.15:9790/'


def test_hermes_runtime_url_prefers_published_host_port(monkeypatch):
    ui = make_service(monkeypatch)

    def inspect(args, **kwargs):
        assert args == ['/custom/container', 'inspect', 'custom-ui']
        return subprocess.CompletedProcess(args, 0, json.dumps([{
            'status': {'state': 'running', 'networks': [{'ipv4Address': '192.168.64.10/24'}]},
            'configuration': {'publishedPorts': [{'hostPort': 9887, 'containerPort': 8787, 'proto': 'tcp'}]},
        }]))

    monkeypatch.setattr(service.subprocess, 'run', inspect)
    assert ui.hermes_runtime_url() == 'http://127.0.0.1:9887/'


def test_hermes_runtime_url_uses_container_ip_without_publish(monkeypatch):
    ui = make_service(monkeypatch)
    # published_host_url() and hermes_runtime_url() each inspect once.
    addresses = iter(['192.168.64.10/24', '192.168.64.10/24',
                      '192.168.64.25/24', '192.168.64.25/24'])

    def inspect(args, **kwargs):
        assert args == ['/custom/container', 'inspect', 'custom-ui']
        return subprocess.CompletedProcess(args, 0, json.dumps([{
            'status': {'state': 'running', 'networks': [{'ipv4Address': next(addresses)}]},
            'configuration': {'publishedPorts': []},
        }]))

    monkeypatch.setattr(service.subprocess, 'run', inspect)
    assert ui.hermes_runtime_url() == 'http://192.168.64.10:9887/'
    assert ui.hermes_runtime_url() == 'http://192.168.64.25:9887/'


def test_native_mode_has_no_runtime_url(monkeypatch):
    ui = make_service(monkeypatch, use_hermes_webui=False)
    def unexpected(*args, **kwargs):
        raise AssertionError('Native mode must not inspect a different deployment')
    monkeypatch.setattr(service.subprocess, 'run', unexpected)
    assert ui.browser_url() == 'http://127.0.0.1:9790/'
    assert ui.hermes_runtime_url() is None


def test_unavailable_container_does_not_change_chat_url(monkeypatch):
    ui = make_service(monkeypatch)
    monkeypatch.setattr(service.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, ''))
    assert ui.browser_url() == 'http://127.0.0.1:9790/'
    assert ui.hermes_runtime_url() == 'http://127.0.0.1:9887/'
