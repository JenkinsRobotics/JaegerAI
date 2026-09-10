"""Local Ollama model command adapter."""

import os

from ..contracts import DelegateRequest
from ..process import CommandSpec, SubprocessDelegateRuntime


def _model() -> str:
    return os.environ.get("JAEGER_OLLAMA_DELEGATE_MODEL", "").strip()


def _available() -> tuple[bool, str]:
    model = _model()
    return (bool(model), "configured" if model else "set JAEGER_OLLAMA_DELEGATE_MODEL")


def _args(request: DelegateRequest, executable: str) -> tuple[str, ...]:
    del executable
    return ("run", _model(), request.prompt)


def create_runtime() -> SubprocessDelegateRuntime:
    return SubprocessDelegateRuntime(
        CommandSpec(
            runtime_id="ollama",
            executables=("ollama",),
            build_args=_args,
            capabilities=frozenset({"inference", "local", "private"}),
            local=True,
            credential_env=frozenset({"OLLAMA_HOST"}),
            availability_check=_available,
        )
    )
