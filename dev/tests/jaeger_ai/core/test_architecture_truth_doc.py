"""Workstream 22 — architecture documentation tells the truth."""
from __future__ import annotations

from pathlib import Path

DOC = Path("docs/architecture/ARCHITECTURE.md")


def test_architecture_doc_exists_and_classifies_capabilities():
    text = DOC.read_text(encoding="utf-8")
    for token in (
        "IMPLEMENTED",
        "EXPERIMENTAL",
        "PLANNED",
        "DEPRECATED",
        "CONTROL PLANE / GATEWAY",
        "PERSISTENT ENTITY RUNTIME",
        "PolicyKernel",
        "ContextCompiler",
        "ONE FACT = ONE AUTHORITATIVE OWNER",
    ):
        assert token in text, f"architecture truth doc missing {token!r}"
    assert "physical iPhone" in text.lower() or "Physical iPhone" in text
    assert "kimi-k2.7-code:cloud" in text
