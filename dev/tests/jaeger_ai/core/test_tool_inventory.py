"""Inventory cannot connect/probe/grant or expose loaded transport credentials."""
from types import SimpleNamespace
import json
from jaeger_ai.core.gateway.tool_inventory import collect
from jaeger_os.core.tools import tool_registry


def test_loaded_inventory_redacts_transport_secrets_without_probing(monkeypatch):
    from jaeger_ai.plugins.mcp import client
    secret = 'owned-fixture-private-value'
    spec = SimpleNamespace(agent_name='mcp__owned__read', server_name='owned', description='Description ' + secret)
    config = SimpleNamespace(headers={'Authorization': secret}, env={'API_KEY': secret}, command='/private/command', url='http://private-endpoint')
    registry = SimpleNamespace(_clients={'owned': SimpleNamespace(config=config)}, list_tools=lambda: [spec])
    monkeypatch.setattr(client, 'get_registry', lambda: registry)
    monkeypatch.setattr(client, 'connection_errors', lambda: {'failed': 'Authorization: ' + secret})
    def forbidden():
        raise AssertionError('Inventory must not probe or execute anything')
    tool = SimpleNamespace(name=spec.agent_name, description=spec.description, toolset='mcp:owned', side_effect='read', permission_tier='explicit', beta=False, dangerous=False, check_fn=forbidden, fn=forbidden)
    monkeypatch.setattr(tool_registry, 'get_tools', lambda: [tool])
    result = collect('owned')
    assert result['count'] == 1 and result['execution_authorized'] is False
    assert result['tools'][0]['availability'] == 'not_probed'
    assert result['servers'] == [{'name': 'owned', 'state': 'loaded_not_probed', 'tool_count': 1}, {'name': 'failed', 'state': 'connection_failed', 'tool_count': 0}]
    wire = json.dumps(result)
    assert secret not in wire and config.command not in wire and config.url not in wire
    assert result['tools'][0]['description'] == 'Description ********'


def test_uninitialized_bridge_does_not_initialize_or_report_connected(monkeypatch):
    from jaeger_ai.plugins.mcp import client
    monkeypatch.setattr(client, 'get_registry', lambda: None)
    monkeypatch.setattr(tool_registry, 'get_tools', lambda: [])
    result = collect()
    assert result['mcp_initialized'] is False and result['servers'] == [] and result['tools'] == []
