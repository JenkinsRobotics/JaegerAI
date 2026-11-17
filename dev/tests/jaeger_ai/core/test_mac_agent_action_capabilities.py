"""Source-only capability advertisement; no server/app is started."""
from types import SimpleNamespace
from jaeger_ai.core.agent_registry.registry import with_roster_flags, _with_hidden


def test_roster_advertises_only_supported_seen_action():
    for role in ('lead', 'specialist', 'runtime'):
        identity = {'id': 'native:jaeger' if role == 'lead' else 'agent:worker', 'name': 'worker', 'role': role}
        record = SimpleNamespace(to_dict=lambda: dict(identity), name='worker', role=role, disabled=False)
        for project in (with_roster_flags, _with_hidden):
            value = project(record)
            assert value['ui_actions'] == {'read': True}
            assert all(value[k] == v for k, v in identity.items())
        assert record.to_dict() == identity




