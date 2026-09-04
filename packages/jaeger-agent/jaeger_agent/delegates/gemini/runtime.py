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
        # Gemini CLI refuses to run in an "untrusted" folder and, headless,
        # there is no interactive prompt to accept one — it just exits. This
        # is the flag its own error message names for automated use. The
        # workspace is one Jaeger chose and already governs through its own
        # permission tiers, so the CLI's separate trust gate adds nothing.
        "--skip-trust",
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
