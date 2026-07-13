"""spotlight.py (agent/tools/spotlight.py) — 0.9.3 mac-native suite.

``mdfind``/``mdls`` invocations are mocked — no real disk index query.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.agent.tools import spotlight
from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


def _mock_mdfind_and_mdls(monkeypatch, paths, mdls_output=""):
    monkeypatch.setattr(spotlight.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(spotlight.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(args, **kwargs):
        if args[0] == "mdfind":
            return _proc(0, stdout="\n".join(paths))
        if args[0] == "mdls":
            return _proc(0, stdout=mdls_output)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(spotlight.subprocess, "run", fake_run)


# ── query construction ───────────────────────────────────────────


def test_kind_screenshot_maps_to_kmditem_predicate():
    q = spotlight._build_query("", "screenshot", None)
    assert q == "kMDItemIsScreenCapture = 1"


def test_kind_pdf_maps_to_content_type_tree():
    q = spotlight._build_query("", "pdf", None)
    assert 'com.adobe.pdf' in q


def test_since_week_maps_to_time_today_offset():
    q = spotlight._build_query("", None, "week")
    assert "$time.today(-7)" in q


def test_since_numeric_days():
    q = spotlight._build_query("", None, "14")
    assert "$time.today(-14)" in q


def test_free_text_query_matches_name_or_content():
    q = spotlight._build_query("invoice", None, None)
    assert "kMDItemDisplayName" in q and "kMDItemTextContent" in q
    assert "invoice" in q


def test_predicates_combine_with_and():
    q = spotlight._build_query("report", "pdf", "week")
    assert " && " in q
    assert q.count(" && ") == 2


# ── spotlight_search end-to-end ──────────────────────────────────


def test_spotlight_search_returns_enriched_results(monkeypatch):
    _mock_mdfind_and_mdls(
        monkeypatch, ["/Users/x/Desktop/Screenshot 1.png"],
        mdls_output=(
            'kMDItemDisplayName     = "Screenshot 1.png"\n'
            'kMDItemContentType     = "public.png"\n'
            'kMDItemFSSize          = 12345\n'
            'kMDItemContentModificationDate = 2026-07-10 10:00:00 +0000\n'
        ),
    )
    result = spotlight.spotlight_search(kind="screenshot", since="week")
    assert result["searched"] is True
    assert result["count"] == 1
    hit = result["results"][0]
    assert hit["path"] == "/Users/x/Desktop/Screenshot 1.png"
    assert hit["name"] == "Screenshot 1.png"
    assert hit["content_type"] == "public.png"


def test_spotlight_search_respects_limit_and_flags_truncated(monkeypatch):
    paths = [f"/tmp/file{i}.txt" for i in range(5)]
    _mock_mdfind_and_mdls(monkeypatch, paths)
    result = spotlight.spotlight_search(query="file", limit=2)
    assert result["count"] == 2
    assert result["truncated"] is True


def test_spotlight_search_empty_query_is_rejected():
    result = spotlight.spotlight_search()
    assert result["searched"] is False
    assert "empty search" in result["error"]


def test_spotlight_search_mdfind_missing_is_actionable(monkeypatch):
    monkeypatch.setattr(spotlight.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(spotlight.shutil, "which", lambda name: None)
    result = spotlight.spotlight_search(query="x")
    assert result["searched"] is False
    assert "mdfind" in result["error"]


def test_spotlight_search_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(spotlight.platform, "system", lambda: "Linux")
    result = spotlight.spotlight_search(query="x")
    assert result["searched"] is False
    assert "macOS" in result["error"]


def test_spotlight_search_mdfind_failure_reported(monkeypatch):
    monkeypatch.setattr(spotlight.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(spotlight.shutil, "which", lambda name: "/usr/bin/mdfind")
    monkeypatch.setattr(spotlight.subprocess, "run",
                        lambda *a, **k: _proc(1, stderr="mdfind: invalid query"))
    result = spotlight.spotlight_search(query="x")
    assert result["searched"] is False
    assert "invalid query" in result["error"]


# ── tier + registration ───────────────────────────────────────────


def test_spotlight_search_is_registered_read_only():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert "spotlight_search" in tools
    assert get_tier(tools["spotlight_search"]) == PermissionTier.READ_ONLY
