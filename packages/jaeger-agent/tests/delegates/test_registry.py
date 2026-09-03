from __future__ import annotations

from jaeger_agent.delegates import DelegateRegistry, RuntimeStatus


class Runtime:
    def __init__(self, runtime_id: str) -> None:
        self.runtime_id = runtime_id


def test_registry_is_sorted_and_rejects_accidental_replacement() -> None:
    registry = DelegateRegistry()
    registry.register(Runtime("grok"))
    registry.register(Runtime("claude"))

    assert [runtime.runtime_id for runtime in registry.list()] == ["claude", "grok"]

    try:
        registry.register(Runtime("claude"))
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate delegate registration was accepted")


def test_private_work_requires_a_local_eligible_runtime() -> None:
    remote = RuntimeStatus(
        available=True, local=False, capabilities=frozenset({"code"}),
    )
    local = RuntimeStatus(
        available=True, local=True, capabilities=frozenset({"code", "research"}),
    )

    assert not DelegateRegistry.eligible(
        remote, required_capabilities=frozenset({"code"}), require_local=True,
    )
    assert DelegateRegistry.eligible(
        local, required_capabilities=frozenset({"code"}), require_local=True,
    )
    assert not DelegateRegistry.eligible(
        local, required_capabilities=frozenset({"browser"}), require_local=False,
    )
