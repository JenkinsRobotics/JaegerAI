from jaeger_agent.delegates.claude.runtime import create_runtime
from jaeger_agent.delegates.contracts import DelegateRequest


def test_claude_delegate_accepts_workspace_edits() -> None:
    runtime = create_runtime()
    request = DelegateRequest(
        task_id="task",
        prompt="fix the fixture",
        idempotency_key="test:task",
    )

    assert runtime.spec.build_args(request, "claude") == (
        "--print",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
    )
