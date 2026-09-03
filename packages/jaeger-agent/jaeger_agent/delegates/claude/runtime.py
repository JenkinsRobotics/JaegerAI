"""Claude Code command adapter."""

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del request, executable
    return ("--print", "--output-format", "json", "--permission-mode", "dontAsk")


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="claude",
            executables=("claude",),
            build_args=_args,
            capabilities=frozenset({"code", "filesystem", "research", "terminal"}),
            local=False,
            credential_env=frozenset({"ANTHROPIC_API_KEY"}),
            prompt_on_stdin=True,
        )
    )
