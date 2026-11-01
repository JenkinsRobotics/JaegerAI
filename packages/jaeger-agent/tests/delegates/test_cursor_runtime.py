from jaeger_agent.delegates.cursor.runtime import create_runtime


def test_cursor_delegate_uses_agent_cli() -> None:
    runtime = create_runtime()
    assert runtime.spec.executables == ("cursor-agent",)
    assert runtime.spec.runtime_id == "cursor"
