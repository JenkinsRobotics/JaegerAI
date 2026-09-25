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
    "docs/CONTINUE_FROM_HERE.md",
    "docs/architecture/THREAT_MODEL.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml",
)


def test_public_review_files_exist():
    for rel in REQUIRED:
        assert Path(rel).is_file(), f"missing public-review file: {rel}"


def test_contributing_points_at_test_tiers_and_the_release_branch():
    text = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "0.13-dev" in text
    assert "dev/scripts/run_tests.sh" in text
    assert "JAEGER_STATE_DIR" in text
    assert "do not merge" in text.lower() or "Do not merge" in text


def test_extension_guide_forbids_core_edits_for_skills():
    text = Path("docs/EXTENSION_GUIDE.md").read_text(encoding="utf-8")
    assert "Do not modify `EntityRuntime`" in text
    assert "jaeger capability validate" in text
    assert "SUPPORTED — NOT LIVE TESTED" in text


def test_continuation_entry_point_is_indexed_and_supersedes_stale_plans():
    continuation = Path("docs/CONTINUE_FROM_HERE.md").read_text(encoding="utf-8")
    docs_index = Path("docs/README.md").read_text(encoding="utf-8")
    assert "Branch:** `0.13-dev`" in continuation
    assert "4124422b15e7f0ca28941774992000b24a151719" in continuation
    assert "P0 — reliable live conversation/execution path" in continuation
    assert "Not yet qualified" in continuation
    assert "CURRENT AUTHORITATIVE" in docs_index
    assert "CONTINUE_FROM_HERE.md" in docs_index
    # These old plans described a pre-Gateway Swift architecture and a
    # superseded 0.9.3 sprint. Git history preserves their evidence.
    assert not Path("jaeger_ai/interfaces/swift/PARITY_PLAN.md").exists()
    assert not Path("dev/docs/roadmap/0.9.3_EVERYDAY_AGENCY_PLAN.md").exists()
