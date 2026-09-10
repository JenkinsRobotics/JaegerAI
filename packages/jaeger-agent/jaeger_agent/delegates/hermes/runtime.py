"""Hermes Agent command adapter, separate from the Hermes WebUI adapter."""

import os
from pathlib import Path

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    if Path(executable).name == "hermes-agent":
        return (f"--query={request.prompt}",)
    return ("chat", "-q", request.prompt)


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="hermes",
            executables=("hermes-agent", "hermes"),
            build_args=_args,
            capabilities=frozenset({"automation", "code", "research", "tools"}),
            local=os.environ.get("JAEGER_HERMES_DELEGATE_LOCAL") == "1",
            credential_env=frozenset(
                {
                    "ANTHROPIC_API_KEY",
                    "GEMINI_API_KEY",
                    "GOOGLE_API_KEY",
                    "NOUS_API_KEY",
                    "OPENAI_API_KEY",
                    "OPENROUTER_API_KEY",
                    "XAI_API_KEY",
                }
            ),
        )
    )
