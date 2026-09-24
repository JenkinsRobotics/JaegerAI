"""Storage invariants; execution/recovery acceptance lives in test_gateway_task_owner."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from jaeger_ai.core.tasks import DurableTask, SqliteDurableTaskStore


def test_concurrent_admission_does_not_replace_progress(tmp_path):
    store = SqliteDurableTaskStore(tmp_path / 'gateway.sqlite3')
    def admit(_):
        return store.admit_task(DurableTask('same', 'jaeger', 'Build report', payload={'execution':{}}))[1]
    with ThreadPoolExecutor(max_workers=4) as workers:
        replayed = list(workers.map(admit, range(16)))
    assert replayed.count(False) == 1
    store.update_task('same', lambda t: t.payload.update(attempt=2))
    assert admit(None)
    assert store.get_task('same').payload['attempt'] == 2


def test_conflicting_execution_is_rejected(tmp_path):
    store = SqliteDurableTaskStore(tmp_path / 'gateway.sqlite3')
    store.admit_task(DurableTask('same', 'jaeger', 'Build', payload={'model':'one'}))
    with pytest.raises(ValueError, match='conflicts'):
        store.admit_task(DurableTask('same', 'jaeger', 'Build', payload={'model':'two'}))


def test_restart_preserves_run_and_cancellation_instead_of_requeueing(tmp_path):
    path = tmp_path / 'gateway.sqlite3'
    store = SqliteDurableTaskStore(path)
    task = DurableTask('same', 'jaeger', 'Build')
    task.cancellation = 'Operator requested cancellation'
    task.payload = {'native_run_id':'run-1', 'attempt':3}
    store.admit_task(task)
    restored = SqliteDurableTaskStore(path).get_task('same')
    assert restored.cancellation == task.cancellation
    assert restored.payload == task.payload
