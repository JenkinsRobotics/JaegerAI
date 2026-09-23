"""Canonical service port facts may not be redefined with different values.

This is not hypothetical. Until 2026-09-14 a dead ``jaeger_ai/contract/ports.py``
declared ``ANIMATION_BRIDGE_DEFAULT_PORT = 9999`` while the live
``jaeger_os/contract/ports.py`` said ``8765``. One constant name, two files, two
answers, and nothing to say which one you had imported.

That is the exact failure mode these tests exist to catch: not a wrong value,
but two plausible values for one name.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from jaeger_ai.contract import ports
from jaeger_os.contract import ports as engine_ports

REPO = pathlib.Path(__file__).resolve().parents[4]
SKIP_PARTS = {"__pycache__", ".build", "vendor", "node_modules", ".git", "worktrees"}
CANONICAL_PORT_NAMES = {
    name for contract in (ports, engine_ports) for name in contract.__all__
    if name.endswith("_PORT")
}


def _port_constants(root: pathlib.Path = REPO) -> dict[str, dict[int, list[str]]]:
    """Definitions of public contract port names, grouped by name and value.

    Generic local names such as ``DEFAULT_PORT`` describe different facts in
    unrelated modules and are intentionally outside this one-definition gate.
    """
    found: dict[str, dict[int, list[str]]] = {}
    for path in root.rglob("*.py"):
        if SKIP_PARTS & set(path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, int):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id not in CANONICAL_PORT_NAMES:
                    continue
                found.setdefault(target.id, {}).setdefault(
                    node.value.value, []
                ).append(str(path.relative_to(root)))
    return found


def test_port_scan_detects_drift_against_annotated_contract(tmp_path):
    (tmp_path / "contract.py").write_text("GATEWAY_PORT: Final = 8810\n")
    (tmp_path / "client.py").write_text("GATEWAY_PORT = 9999\nDEFAULT_PORT = 8000\n")
    definitions = _port_constants(tmp_path)
    assert set(definitions["GATEWAY_PORT"]) == {8810, 9999}
    assert "DEFAULT_PORT" not in definitions


def test_no_port_constant_has_two_different_values() -> None:
    clashes = {
        name: values
        for name, values in _port_constants().items()
        if len(values) > 1
    }
    lines: list[str] = []
    for name, values in sorted(clashes.items()):
        lines.append(f"{name} is defined with {len(values)} different values:")
        for value, files in sorted(values.items()):
            lines.append(f"    = {value}  in  {', '.join(sorted(files))}")
    assert not clashes, "\n".join(lines)


def test_every_port_the_contract_names_is_distinct() -> None:
    """Two services on one port is a startup failure nobody reads the log for."""
    named = {
        name: getattr(ports, name)
        for name in ports.__all__
        if name.endswith("_PORT")
    }
    by_value: dict[int, list[str]] = {}
    for name, value in named.items():
        by_value.setdefault(value, []).append(name)
    collisions = {v: n for v, n in by_value.items() if len(n) > 1}
    assert not collisions, f"same port assigned to several services: {collisions}"


@pytest.mark.parametrize(
    ("module_path", "attr", "expected"),
    [
        ("jaeger_ai.features.agentgateway.constants", "MCP_GATEWAY_PORT", ports.MCP_GATEWAY_PORT),
        ("jaeger_ai.features.agentgateway.constants", "A2A_GATEWAY_PORT", ports.A2A_GATEWAY_PORT),
        ("jaeger_ai.interfaces.a2a_server", "A2A_PORT", ports.A2A_PORT),
    ],
)
def test_live_modules_agree_with_the_contract(module_path, attr, expected) -> None:
    """These still hold their own literal; the contract must match what runs.

    They are deliberately not rewritten to import the contract — each is a
    long-standing public name other code reads. The test is the join instead,
    so the two cannot drift without CI saying so.
    """
    import importlib
    module = importlib.import_module(module_path)
    assert getattr(module, attr) == expected, (
        f"{module_path}.{attr} and jaeger_ai.contract.ports disagree. "
        f"Change both, or make one import the other."
    )


def test_the_chat_spine_ports_are_what_the_docs_promise() -> None:
    """AGENTS.md's topology table is the first thing a newcomer reads."""
    assert ports.GATEWAY_PORT == 8810
    assert ports.WEBUI_PORT == 8790
    assert ports.WEBUI_ADAPTER_PORT == 8791
    topology = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    for port in (ports.GATEWAY_PORT, ports.WEBUI_PORT):
        assert str(port) in topology, f"port {port} is not in AGENTS.md's topology"


def test_framework_protocol_urls_derive_from_the_port_contract() -> None:
    assert ports.MCP_GATEWAY_URL == f"http://{ports.LOOPBACK}:{ports.MCP_GATEWAY_PORT}/mcp"
    assert ports.MCP_CONTAINER_GATEWAY_URL == (
        f"http://{ports.CONTAINER_HOST}:{ports.MCP_GATEWAY_PORT}/mcp"
    )
    assert ports.MCP_HTTP_URL == f"http://{ports.LOOPBACK}:{ports.MCP_HTTP_PORT}/mcp"
    assert ports.A2A_GATEWAY_URL == f"http://{ports.LOOPBACK}:{ports.A2A_GATEWAY_PORT}"
    assert ports.A2A_CONTAINER_GATEWAY_URL == (
        f"http://{ports.CONTAINER_HOST}:{ports.A2A_GATEWAY_PORT}"
    )
    assert ports.A2A_URL == f"http://{ports.LOOPBACK}:{ports.A2A_PORT}"


def test_hardware_ports_are_not_redeclared_here() -> None:
    """Engine facts live in jaeger_os.contract; copying them back is the bug."""
    assert not [n for n in ports.__all__ if "ANIMATION" in n or "JP01" in n], (
        "animation-bridge and JP01 ports belong to jaeger_os.contract.ports. "
        "A second declaration here is what produced the 9999-vs-8765 split."
    )
