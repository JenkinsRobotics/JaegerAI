from jaeger_agent.delegates import DelegateRegistry, register_builtin_delegates


def test_builtin_delegate_features_are_independently_registered() -> None:
    registry = register_builtin_delegates(DelegateRegistry())
    assert [runtime.runtime_id for runtime in registry.list()] == [
        "claude",
        "codex",
        "cursor",
        "gemini",
        "grok",
        "hermes",
        "ollama",
        "openclaw",
        "opencode",
    ]


def test_only_explicit_local_runtime_handles_private_work(monkeypatch) -> None:
    monkeypatch.delenv("JAEGER_HERMES_DELEGATE_LOCAL", raising=False)
    monkeypatch.delenv("JAEGER_OPENCLAW_DELEGATE_LOCAL", raising=False)
    registry = register_builtin_delegates(DelegateRegistry())
    locality = {runtime.runtime_id: runtime.spec.local for runtime in registry.list()}
    assert locality["ollama"] is True
    assert all(not locality[name] for name in locality if name != "ollama")
