from jaeger_agent.delegates.health import (
    DelegateObservation,
    InMemoryDelegateHealthStore,
)


def test_effectiveness_uses_prior_and_capability_history() -> None:
    store = InMemoryDelegateHealthStore()
    store.record(DelegateObservation("codex", True, 100, capability="code", quality=0.9))
    store.record(DelegateObservation("codex", False, 300, capability="code", quality=0.3))

    score = store.effectiveness("codex", "code")
    assert score.samples == 2
    assert score.successes == 1
    assert score.success_rate == 0.5
    assert score.mean_latency_ms == 200
    assert score.mean_quality == 0.6
