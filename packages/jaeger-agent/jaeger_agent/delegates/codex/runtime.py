"""Codex CLI command adapter."""

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _workspace_write_args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del request, executable
    return (
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "-",
    )


def _read_only_args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del request, executable
    return (
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-",
    )


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="codex",
            executables=("codex",),
            build_args=_workspace_write_args,
            capabilities=frozenset({"code", "filesystem", "research", "terminal"}),
            local=False,
            credential_env=frozenset({"OPENAI_API_KEY"}),
            prompt_on_stdin=True,
        )
    )


def create_read_only_runtime() -> SubprocessDelegateRuntime:
    """Codex CLI runtime that enforces the CLI's read-only sandbox."""
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="codex",
            executables=("codex",),
            build_args=_read_only_args,
            capabilities=frozenset(
                {"code", "filesystem", "research", "terminal", "read_only_enforced"}
            ),
            local=False,
            credential_env=frozenset({"OPENAI_API_KEY"}),
            prompt_on_stdin=True,
        )
    )
