"""Strict AST layering guard: standalone packages NEVER import jaeger_ai or retired monoliths."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

STANDALONE_PACKAGE_SRC_ROOTS = [
    "packages/jaeger-contracts/src",
    "packages/jaeger-events/src",
    "packages/jaeger-gateway/src",
    "packages/jaeger-reliability/src",
    "packages/jaeger-models/src",
    "packages/jaeger-authority/src",
    "packages/jaeger-memory/src",
    "packages/jaeger-tools/src",
    "packages/jaeger-lsp/src",
    "packages/jaeger-checkpoints/src",
    "packages/jaeger-loop/src",
    "packages/jaeger-orchestration/src",
    "packages/jaeger-skills/src",
    "packages/jaeger-cognition/src",
    "packages/jaeger-avatar/src",
    "packages/jaeger-business/src",
    "packages/jaeger-youtube/src",
    "packages/jaeger-channels/src",
    "packages/jaeger-embodiment-minecraft/src",
    "packages/jaeger-hardware/src",
    "packages/jaeger-realtime/src",
    "packages/jaeger-vision/src",
    "packages/jaeger-evals/src",
    "packages/jaeger-protocols/src",
    "packages/jaeger-mcp/src",
    "packages/jaeger-macos/src",
]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_standalone_packages_have_zero_upward_or_legacy_imports() -> None:
    forbidden = {"jaeger_ai", "jaeger_agent", "jaeger_os"}
    violations: list[str] = []
    for rel_root in STANDALONE_PACKAGE_SRC_ROOTS:
        root = REPO / rel_root
        assert root.is_dir(), f"missing standalone package root: {rel_root}"
        for py in sorted(root.rglob("*.py")):
            bad = sorted(_imported_modules(py) & forbidden)
            if bad:
                violations.append(f"{py.relative_to(REPO)}: {bad}")
    assert not violations, "Forbidden upward/legacy imports:\n" + "\n".join(violations)


def test_legacy_monoliths_are_deleted() -> None:
    assert not (REPO / "packages/jaeger-agent").exists()
    assert not (REPO / "packages/jaeger-os").exists()
    assert not (REPO / "jaeger_ai/main.py").exists()
    assert not (REPO / "jaeger_ai/core/gateway/session_store.py").exists()
