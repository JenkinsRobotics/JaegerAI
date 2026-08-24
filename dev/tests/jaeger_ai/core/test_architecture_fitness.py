"""Architecture fitness — keep replaceability from regressing."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_agent_loop_does_not_import_provider_sdks():
    """The loop talks to ProviderAdapter; SDKs stay in adapters/."""
    loop_dir = REPO / "packages/jaeger-agent/jaeger_agent/loop"
    banned = {"openai", "anthropic", "google", "ollama", "mlx_lm"}
    offenders: list[str] = []
    for path in loop_dir.glob("*.py"):
        hit = _imports(path) & banned
        if hit:
            offenders.append(f"{path.name}: {sorted(hit)}")
    assert offenders == [], offenders


def test_memory_facade_does_not_import_provider_sdks():
    mem = REPO / "packages/jaeger-agent/jaeger_agent/memory"
    banned = {"openai", "anthropic", "fastapi"}
    offenders: list[str] = []
    for path in mem.glob("*.py"):
        hit = _imports(path) & banned
        if hit:
            offenders.append(f"{path.name}: {sorted(hit)}")
    assert offenders == [], offenders


def test_provider_adapter_abc_is_the_swap_point():
    from jaeger_agent.adapters.base import ProviderAdapter
    from jaeger_agent.adapters.openai import OpenAIAdapter
    from jaeger_agent.memory.port import MemoryStore
    from jaeger_agent.memory.in_memory import InMemoryMemoryStore

    assert issubclass(OpenAIAdapter, ProviderAdapter)
    assert isinstance(InMemoryMemoryStore(), MemoryStore)
