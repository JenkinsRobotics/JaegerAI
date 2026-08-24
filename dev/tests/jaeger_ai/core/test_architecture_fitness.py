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


def test_agent_loop_routes_execution_through_tool_executor():
    """The loop selects tools but cannot invoke concrete handlers directly."""
    loop = REPO / "packages/jaeger-agent/jaeger_agent/loop/jaeger_agent.py"
    tree = ast.parse(loop.read_text(encoding="utf-8"))
    direct_dispatches = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "dispatch"
    ]
    assert direct_dispatches == [], (
        "JaegerAgent bypasses ToolExecutor at lines "
        f"{direct_dispatches}"
    )


def test_ledger_executor_routes_external_tools_through_once():
    """Authoritative side effects go through EffectLedger.once, not a
    naked dispatch. The loop stays DirectToolExecutor by default; the
    host that wants at-most-once sends injects LedgerToolExecutor."""
    path = REPO / "packages/jaeger-agent/jaeger_agent/tool_executor.py"
    source = path.read_text(encoding="utf-8")
    assert "self._ledger.once(" in source
    assert "AUTHORITATIVE_SIDE_EFFECTS" in source


def test_send_email_declares_external_side_effect():
    import jaeger_agent.tools  # noqa: F401
    from jaeger_os.core.tools.tool_registry import get_tool

    tool = get_tool("send_email")
    assert tool.side_effect == "external"


def test_provider_adapter_abc_is_the_swap_point():
    from jaeger_agent.adapters.base import ProviderAdapter
    from jaeger_agent.adapters.openai import OpenAIAdapter
    from jaeger_agent.memory.port import MemoryStore
    from jaeger_agent.memory.in_memory import InMemoryMemoryStore

    assert issubclass(OpenAIAdapter, ProviderAdapter)
    assert isinstance(InMemoryMemoryStore(), MemoryStore)
