"""Discovery must follow instance settings, not the machine's other deployment."""
import json
import subprocess

from jaeger_ai.features.hermes_webui import service


def make_service(monkeypatch, **changes):
    config = dict(instance='selected', layout=None, use_hermes_webui=True,
                  engine='/custom/container', hermes_webui_container='custom-ui',
                  hermes_webui_port=9887, adapter_port=9791, jaeger_webui_port=9790)
    config.update(changes)
    monkeypatch.setattr(service, '_load_containers_config', lambda instance: config)
    monkeypatch.delenv('CONTAINER_CLI', raising=False)
    return service.HermesWebUIService('selected')


def test_discovery_respects_container_engine_port_mapping_and_ip_changes(monkeypatch):
    ui = make_service(monkeypatch)
    addresses = iter(['192.168.64.10/24', '192.168.64.25/24'])

    def inspect(args, **kwargs):
        assert args == ['/custom/container', 'inspect', 'custom-ui']
        return subprocess.CompletedProcess(args, 0, json.dumps([{
            'status': {'state': 'running', 'networks': [{'ipv4Address': next(addresses)}]},
            'configuration': {'publishedPorts': [{'hostPort': 9887, 'containerPort': 8787, 'proto': 'tcp'}]},
        }]))

    monkeypatch.setattr(service.subprocess, 'run', inspect)
    assert ui.browser_url() == 'http://192.168.64.10:8787/'
    assert ui.browser_url() == 'http://192.168.64.25:8787/'


def test_native_mode_uses_configured_port_without_container_discovery(monkeypatch):
    ui = make_service(monkeypatch, use_hermes_webui=False)
    def unexpected(*args, **kwargs):
        raise AssertionError('Native mode must not inspect a different deployment')
    monkeypatch.setattr(service.subprocess, 'run', unexpected)
    assert ui.browser_url() == 'http://127.0.0.1:9790/'


def test_unavailable_container_does_not_silently_switch_to_native_ui(monkeypatch):
    ui = make_service(monkeypatch)
    monkeypatch.setattr(service.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, ''))
    assert ui.browser_url() == 'http://127.0.0.1:9887/'
