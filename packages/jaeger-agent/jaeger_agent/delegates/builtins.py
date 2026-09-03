"""Registration of Jaeger's independently packaged delegate features."""

from .claude import create_runtime as create_claude
from .codex import create_runtime as create_codex
from .cursor import create_runtime as create_cursor
from .gemini import create_runtime as create_gemini
from .grok import create_runtime as create_grok
from .hermes import create_runtime as create_hermes
from .ollama import create_runtime as create_ollama
from .openclaw import create_runtime as create_openclaw
from .opencode import create_runtime as create_opencode
from .registry import DelegateRegistry, get_delegate_registry


def register_builtin_delegates(
    registry: DelegateRegistry | None = None,
) -> DelegateRegistry:
    target = registry or get_delegate_registry()
    for factory in (
        create_claude,
        create_codex,
        create_cursor,
        create_gemini,
        create_grok,
        create_hermes,
        create_ollama,
        create_openclaw,
        create_opencode,
    ):
        target.register(factory(), replace=True)
    return target
