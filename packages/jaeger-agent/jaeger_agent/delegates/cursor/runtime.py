"""Cursor CLI command adapter."""

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del executable
    return ("-p", request.prompt)


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="cursor",
            executables=("cursor",),
            build_args=_args,
            capabilities=frozenset({"code", "filesystem", "terminal"}),
            local=False,
            credential_env=frozenset({"CURSOR_API_KEY"}),
        )
    )
