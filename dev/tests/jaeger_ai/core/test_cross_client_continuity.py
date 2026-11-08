"""Independent authenticated clients against an owned real runtime; scripted model only."""
from dev.tests.fixtures.owned_gateway import OwnedGateway


def test_ide_phone_and_cli_continue_one_durable_session_without_replaying_work(tmp_path):
    owner = OwnedGateway(tmp_path)
    try:
        owner.start()
        identity = owner.identity
        _, session = owner.request('/v1/sessions', {'session_id':'cross-client','profile':'jaeger'}, caller='ide')
        assert session['session_id'] == 'cross-client'
        body = {'text':'Say CONTRACT-ANSWER', 'request_id':'ide-original'}
        owner.request('/v1/sessions/cross-client/turns', body, caller='ide')
        first = owner.wait_for_terminal('cross-client','ide-original')
        assert first['status'] == 'completed'
        _, phone = owner.request('/v1/sessions/cross-client', caller='webui')
        assert [m['role'] for m in phone['messages']] == ['user','assistant']
        assert phone['messages'][-1]['request_id'] == 'ide-original'
        # A lost admission reply can be retried using the original identity;
        # another client observes its receipt rather than creating another turn.
        owner.request('/v1/sessions/cross-client/turns', body, caller='ide')
        _, observed = owner.request('/v1/sessions/cross-client/requests/ide-original', caller='webui')
        assert observed['turn_id'] == first['turn_id']
        _, events = owner.request('/v1/sessions/cross-client/events', caller='webui')
        terminal = [event for event in events['events'] if event['event']=='turn.finish' and event['data'].get('request_id')=='ide-original']
        assert len(terminal) == 1
        owner.stop(); owner.start()
        assert owner.identity == identity
        _, resumed = owner.request('/v1/sessions/cross-client', caller='cli')
        assert resumed['messages'] == phone['messages']
        owner.request('/v1/sessions/cross-client/turns', {'text':'Continue with CONTRACT-ANSWER','request_id':'phone-next'}, caller='webui')
        assert owner.wait_for_terminal('cross-client','phone-next')['status'] == 'completed'
        _, final = owner.request('/v1/sessions/cross-client', caller='ide')
        assert [m['role'] for m in final['messages']] == ['user','assistant','user','assistant']
        assert {m['request_id'] for m in final['messages']} == {'ide-original','phone-next'}
    finally:
        owner.stop()
