"""OpenClaw gateway command adapter."""

import os

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del executable
    return (
        "agent",
        "--message",
        request.prompt,
        "--json",
        "--timeout",
        str(request.timeout_seconds),
    )


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="openclaw",
            executables=("openclaw",),
            build_args=_args,
            capabilities=frozenset({"automation", "code", "messaging", "research"}),
            local=os.environ.get("JAEGER_OPENCLAW_DELEGATE_LOCAL") == "1",
            credential_env=frozenset(
                {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"}
            ),
        )
    )
