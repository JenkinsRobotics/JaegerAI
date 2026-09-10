"""Native model workers must inherit this turn's scoped stream destination."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import threading

import pytest

from jaeger_agent.loop.interrupt import interruptible_call
from jaeger_ai.main import current_turn_sink, stream_delta_sink


@pytest.mark.parametrize('persistent', [False, True])
def test_model_worker_preserves_and_releases_the_current_stream_scope(persistent):
    first, second = [], []
    def produce():
        sink = current_turn_sink('stream_delta_sink')
        if sink is not None:
            sink('native delta')
        return 'final'
    with ThreadPoolExecutor(max_workers=1) if persistent else nullcontext(None) as executor:
        with stream_delta_sink(first.append):
            assert interruptible_call(produce, threading.Event(), executor=executor) == 'final'
        with stream_delta_sink(second.append):
            interruptible_call(produce, threading.Event(), executor=executor)
        interruptible_call(produce, threading.Event(), executor=executor)
    assert first == ['native delta']
    assert second == ['native delta']


def test_parallel_native_tools_inherit_the_owning_turn_context(monkeypatch):
    from jaeger_agent.loop.jaeger_agent import JaegerAgent
    agent = object.__new__(JaegerAgent)
    received, results = [], []
    monkeypatch.setattr(agent, '_prepare_dispatch', lambda name: {'sig': name})
    def execute(prep):
        sink = current_turn_sink('stream_delta_sink')
        if sink:
            sink(prep['sig'])
        return prep['sig']
    monkeypatch.setattr(agent, '_execute_prepared', execute)
    monkeypatch.setattr(agent, '_finish_dispatch', lambda prep, result: results.append(result))
    with stream_delta_sink(received.append):
        agent._dispatch_parallel(['one', 'two'])
    assert sorted(received) == ['one', 'two']
    assert results == ['one', 'two']
