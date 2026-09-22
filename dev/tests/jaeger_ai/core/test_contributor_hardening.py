"""Workstream 25 — contributor and public-review files exist and stay honest."""
from __future__ import annotations

from pathlib import Path

REQUIRED = (
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "docs/EXTENSION_GUIDE.md",
    "docs/architecture/ARCHITECTURE.md",
    "docs/architecture/TEST_ARCHITECTURE.md",
    "docs/architecture/THREAT_MODEL.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml",
)


def test_public_review_files_exist():
    for rel in REQUIRED:
        assert Path(rel).is_file(), f"missing public-review file: {rel}"


def test_contributing_points_at_test_tiers_and_pinocchio():
    text = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "pinocchio" in text
    assert "dev/scripts/run_tests.sh" in text
    assert "JAEGER_STATE_DIR" in text
    assert "do not merge" in text.lower() or "Do not merge" in text


def test_extension_guide_forbids_core_edits_for_skills():
    text = Path("docs/EXTENSION_GUIDE.md").read_text(encoding="utf-8")
    assert "Do not modify `EntityRuntime`" in text
    assert "jaeger capability validate" in text
    assert "SUPPORTED — NOT LIVE TESTED" in text
