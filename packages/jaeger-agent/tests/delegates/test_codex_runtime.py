from jaeger_agent.delegates.codex.runtime import create_read_only_runtime, create_runtime
from jaeger_agent.delegates.contracts import DelegateRequest


def _request() -> DelegateRequest:
    return DelegateRequest(
        task_id="task",
        prompt="inspect the fixture",
        idempotency_key="test:task",
    )


def test_codex_read_only_runtime_enforces_the_read_only_sandbox() -> None:
    runtime = create_read_only_runtime()

    assert "read_only_enforced" in runtime.spec.capabilities
    assert runtime.spec.build_args(_request(), "codex") == (
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-",
    )


def test_default_codex_runtime_does_not_claim_read_only() -> None:
    runtime = create_runtime()

    assert "read_only_enforced" not in runtime.spec.capabilities
    assert "workspace-write" in runtime.spec.build_args(_request(), "codex")
