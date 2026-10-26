"""Workstream 25 — contributor and public-review files exist and stay honest."""
from __future__ import annotations

import re
from pathlib import Path

REQUIRED = (
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "docs/EXTENSION_GUIDE.md",
    "docs/architecture/ARCHITECTURE.md",
    "docs/architecture/TEST_ARCHITECTURE.md",
    "docs/PRODUCT.md",
    "docs/STACK.md",
    "docs/TRUST.md",
    "docs/REBUILD.md",
    "docs/CLEANUP.md",
    "docs/architecture/THREAT_MODEL.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml",
)


def test_public_review_files_exist():
    for rel in REQUIRED:
        assert Path(rel).is_file(), f"missing public-review file: {rel}"


def _current_branch() -> str:
    import subprocess

    out = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_contributing_points_at_test_tiers_and_the_release_branch():
    text = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
    assert _current_branch() in text
    assert "dev/scripts/run_tests.sh" in text
    assert "JAEGER_STATE_DIR" in text
    assert "do not rewrite published git history" in text.lower()


def test_extension_guide_forbids_core_edits_for_skills():
    text = Path("docs/EXTENSION_GUIDE.md").read_text(encoding="utf-8")
    assert "Do not modify `EntityRuntime`" in text
    assert "jaeger capability validate" in text
    assert "SUPPORTED — NOT LIVE TESTED" in text


def test_product_definition_is_indexed_and_supersedes_stale_plans():
    """2026-10-22: docs/CONTINUE_FROM_HERE.md was superseded by docs/PRODUCT.md
    and moved to the Desktop (see docs/CLEANUP.md). The indexed entry point is
    now the product definition; stale plans stay out of the tree."""
    product = Path("docs/PRODUCT.md").read_text(encoding="utf-8")
    docs_index = Path("docs/README.md").read_text(encoding="utf-8")
    assert "Current product definition, 2026-10-22" in product or "what it is" in product.lower()
    assert "PRODUCT.md" in docs_index
    assert "CURRENT AUTHORITATIVE" in docs_index
    # The docs index may mention the removed file only as cleanup history,
    # never as a link to a kept doc.
    assert "docs/CONTINUE_FROM_HERE.md](CONTINUE_FROM_HERE.md)" not in docs_index
    assert "](CONTINUE_FROM_HERE.md)" not in docs_index
    # These old plans described a pre-Gateway Swift architecture and a
    # superseded 0.9.3 sprint. Git history preserves their evidence.
    assert not Path("jaeger_ai/interfaces/swift/PARITY_PLAN.md").exists()
    assert not Path("dev/docs/roadmap/0.9.3_EVERYDAY_AGENCY_PLAN.md").exists()
    # The moved entry-point file must not silently reappear in the tree.
    assert not Path("docs/CONTINUE_FROM_HERE.md").exists()
