"""Gemini CLI command adapter."""

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del executable
    return (
        "--prompt",
        request.prompt,
        "--output-format",
        "json",
        "--approval-mode",
        "auto_edit",
    )


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="gemini",
            executables=("gemini",),
            build_args=_args,
            capabilities=frozenset({"code", "filesystem", "research", "terminal"}),
            local=False,
            credential_env=frozenset({"GEMINI_API_KEY", "GOOGLE_API_KEY"}),
        )
    )
