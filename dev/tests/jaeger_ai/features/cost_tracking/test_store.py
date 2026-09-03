from jaeger_ai.features.cost_tracking import CostStore


def test_budget_blocks_projected_overspend_and_persists(tmp_path) -> None:
    path = tmp_path / "costs.db"
    store = CostStore(path)
    store.set_limit("codex", "all", 1.0)
    assert store.authorize("codex", 0.75).allowed
    store.record(runtime_id="codex", cost_usd=0.75, input_tokens=10)
    decision = CostStore(path).authorize("codex", 0.30)
    assert not decision.allowed
    assert decision.spent_usd == 0.75
    assert decision.projected_usd == 1.05


def test_global_budget_counts_every_runtime(tmp_path) -> None:
    store = CostStore(tmp_path / "costs.db")
    store.set_limit("global", "all", 1.0)
    store.record(runtime_id="claude", cost_usd=0.6)
    store.record(runtime_id="codex", cost_usd=0.3)
    assert not store.authorize("grok", 0.2).allowed
    store.close()
