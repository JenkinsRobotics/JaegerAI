"""OpenCode command adapter."""

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del executable
    return ("run", "--format", "json", request.prompt)


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="opencode",
            executables=("opencode",),
            build_args=_args,
            capabilities=frozenset({"code", "filesystem", "terminal"}),
            local=False,
            credential_env=frozenset(
                {
                    "ANTHROPIC_API_KEY",
                    "GOOGLE_API_KEY",
                    "OPENAI_API_KEY",
                    "OPENROUTER_API_KEY",
                }
            ),
        )
    )
