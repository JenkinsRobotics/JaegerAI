"""Isolated regressions from the Roundtable audit; no native models or state."""
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from jaeger_ai.interfaces.a2a_server import JaegerBridgeExecutor










def test_a2a_unknown_cancel_never_issues_global_control():
    calls = []
    executor = JaegerBridgeExecutor(SimpleNamespace(control=lambda *a, **k: calls.append((a,k))))
    with pytest.raises(ValueError, match='active'):
        asyncio.run(executor.cancel(SimpleNamespace(current_task=SimpleNamespace(id='unknown')), None))
    assert calls == []


def test_a2a_cancel_owns_native_turn_and_preserves_other_task():
    from a2a.helpers import new_task_from_user_message, new_text_message
    from a2a.server.events import EventQueueLegacy
    from a2a.types import Role

    entered = {name: threading.Event() for name in ('A', 'B')}
    releases = {name: threading.Event() for name in ('A', 'B')}
    turn_ids, controls = {}, []
    class Bridge:
        def turn(self, text, session, *, on_event, turn_id, gateway_caller):
            assert gateway_caller == 'a2a' and session.startswith('a2a:')
            turn_ids[text] = turn_id
            on_event({'type': 'queued'})
            entered[text].set()
            assert releases[text].wait(3)
            return {'text': text}
        def control(self, op, **payload):
            controls.append((op, payload))
            assert payload['turn_id'] == turn_ids['A']
            releases['A'].set()
    executor = JaegerBridgeExecutor(Bridge())
    contexts = {}
    for name in ('A', 'B'):
        message = new_text_message(name, role=Role.ROLE_USER)
        contexts[name] = SimpleNamespace(current_task=new_task_from_user_message(message), message=message)
    async def check():
        tasks = {name: asyncio.create_task(executor.execute(ctx, EventQueueLegacy())) for name, ctx in contexts.items()}
        try:
            for name in ('A', 'B'):
                assert await asyncio.to_thread(entered[name].wait, 2)
            await executor.cancel(contexts['A'], None)
            await asyncio.wait_for(tasks['A'], 2)
            assert not tasks['B'].done()
        finally:
            for release in releases.values(): release.set()
            await asyncio.gather(*tasks.values())
    asyncio.run(check())
    assert controls == [('cancel', {'turn_id': turn_ids['A']})]


