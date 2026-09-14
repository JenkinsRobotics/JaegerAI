from jaeger_ai.features.webui.adapter.profile_catalog import ProfileCatalog


def test_catalog_matches_execution_owners_and_reports_member_failure():
    from jaeger_ai.features.webui.adapter.profile_runner import canonical_profile
    states = {'hermes': True, 'jaeger': True, 'openclaw': False}
    catalog = ProfileCatalog(lambda name: states[name], ttl=0)
    rows = catalog.list()
    assert [p['name'] for p in rows] == ['default', 'jaeger', 'openclaw', 'roundtable']
    assert [p['display_name'] for p in rows] == ['Hermes Agent', 'Jaeger AI', 'OpenClaw', 'Roundtable']
    assert all(canonical_profile(p['name']) == p['runtime'] for p in rows)
    assert [p['gateway_running'] for p in rows] == [True, True, False, False]
    assert rows[-1]['runtime_status'] == 'Unavailable: OpenClaw'
    states['openclaw'] = True
    assert all(p['gateway_running'] for p in catalog.list())


def test_probe_failure_is_unavailable_and_cache_does_not_leak_mutations():
    def probe(name):
        if name == 'hermes':
            raise ConnectionError('private diagnostic')
        return True
    catalog = ProfileCatalog(probe)
    rows = catalog.list()
    assert not rows[0]['gateway_running']
    assert 'private diagnostic' not in str(rows)
    rows[0]['gateway_running'] = True
    assert not catalog.list()[0]['gateway_running']
