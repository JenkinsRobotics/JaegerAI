"""Codex CLI command adapter."""

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del request, executable
    return (
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "-",
    )


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="codex",
            executables=("codex",),
            build_args=_args,
            capabilities=frozenset({"code", "filesystem", "research", "terminal"}),
            local=False,
            credential_env=frozenset({"OPENAI_API_KEY"}),
            prompt_on_stdin=True,
        )
    )
