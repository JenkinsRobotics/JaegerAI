"""Grok Build command adapter."""

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del executable
    args = [
        "--single",
        request.prompt,
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
    ]
    if request.workspace is not None:
        args.extend(("--cwd", str(request.workspace)))
    return tuple(args)


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="grok",
            executables=("grok",),
            build_args=_args,
            capabilities=frozenset({"code", "filesystem", "research", "terminal"}),
            local=False,
            credential_env=frozenset({"XAI_API_KEY"}),
        )
    )
