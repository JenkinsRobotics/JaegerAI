"""Version parsing + latest-release comparison (network-free parts)."""

from __future__ import annotations

import json

from jaeger_ai.core import version_check as V


def test_parse_strips_v_and_suffix():
    assert V.parse_version("0.6.0") == (0, 6, 0)
    assert V.parse_version("v0.6.0") == (0, 6, 0)
    assert V.parse_version("0.6.0-rc1") == (0, 6, 0)
    assert V.parse_version("garbage") == ()      # unparseable sorts lowest


def test_compare_is_numeric_not_lexical():
    # The bug a string compare would hit: "0.10.0" < "0.9.0" lexically.
    assert V.is_newer("0.10.0", "0.9.0")
    assert V.is_newer("0.6.0", "0.5.2")
    assert not V.is_newer("0.5.2", "0.5.2")
    assert not V.is_newer("0.5.1", "0.5.2")


def test_pick_latest_ignores_junk_and_picks_highest():
    assert V.pick_latest(["0.5.2", "0.6.0", "0.5.10"]) == "0.6.0"
    assert V.pick_latest(["0.5.9", "0.5.10"]) == "0.5.10"     # numeric
    assert V.pick_latest(["nightly", "0.6.0"]) == "0.6.0"      # junk dropped
    assert V.pick_latest([]) is None
    assert V.pick_latest(["nope", "nightly"]) is None


def test_update_status_shape(monkeypatch):
    import jaeger_ai
    # newer available
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: "99.0.0")
    st = V.update_status()
    assert st["current"] == jaeger_ai.__version__
    assert st["latest"] == "99.0.0"
    assert st["available"] is True
    # same version → not available
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: jaeger_ai.__version__)
    assert V.update_status()["available"] is False
    # offline → latest None, not available, never raises
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: None)
    off = V.update_status()
    assert off["latest"] is None and off["available"] is False


def test_repo_slug_default_and_from_env(monkeypatch):
    monkeypatch.delenv("JAEGER_REPO_URL", raising=False)
    assert V.repo_slug() == "JenkinsRobotics/JROS"
    monkeypatch.setenv("JAEGER_REPO_URL", "https://github.com/acme/fork.git")
    assert V.repo_slug() == "acme/fork"


# ── cached_update_status (the app-bridge's check_update query) ─────────────


class _Layout:
    """Minimal stand-in for InstanceLayout — cached_update_status only
    reads ``.root``."""
    def __init__(self, root):
        self.root = root


def test_cached_update_status_fail_soft_no_network(tmp_path, monkeypatch):
    """No network (latest_version -> None): available False, never raises,
    notes_url absent."""
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: None)
    lay = _Layout(tmp_path / "inst")
    st = V.cached_update_status(lay)
    assert st["available"] is False
    assert st["latest"] is None
    assert st["notes_url"] is None
    import jaeger_ai
    assert st["current"] == jaeger_ai.__version__


def test_cached_update_status_shape_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: "99.0.0")
    lay = _Layout(tmp_path / "inst")
    st = V.cached_update_status(lay)
    assert st["available"] is True
    assert st["latest"] == "99.0.0"
    assert st["notes_url"] == "https://github.com/JenkinsRobotics/JROS/releases/tag/99.0.0"


def test_cached_update_status_reuses_cache_within_ttl(monkeypatch, tmp_path):
    """A second call inside the TTL must NOT hit the network again — the
    tray-poll cost this cache exists for."""
    calls = []
    monkeypatch.setattr(V, "latest_version",
                        lambda *a, **k: calls.append(1) or "1.0.0")
    lay = _Layout(tmp_path / "inst")
    st1 = V.cached_update_status(lay, now=1000.0)
    st2 = V.cached_update_status(lay, now=1000.0 + 60)   # 1 min later, well within TTL
    assert len(calls) == 1
    assert st1 == st2


def test_cached_update_status_refetches_after_ttl(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(V, "latest_version",
                        lambda *a, **k: calls.append(1) or "1.0.0")
    lay = _Layout(tmp_path / "inst")
    V.cached_update_status(lay, ttl_s=100, now=1000.0)
    V.cached_update_status(lay, ttl_s=100, now=1000.0 + 200)   # past the TTL
    assert len(calls) == 2


def test_cached_update_status_writes_cache_file_under_run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: "1.2.3")
    lay = _Layout(tmp_path / "inst")
    V.cached_update_status(lay, now=42.0)
    cache = tmp_path / "inst" / "run" / "update_check.json"
    assert cache.is_file()
    payload = json.loads(cache.read_text())
    assert payload == {"checked_at": 42.0, "latest": "1.2.3"}


def test_cached_update_status_none_layout_never_caches_or_crashes(monkeypatch):
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: "1.0.0")
    st = V.cached_update_status(None)
    assert st["latest"] == "1.0.0"


def test_cached_update_status_corrupt_cache_degrades_to_live_check(tmp_path, monkeypatch):
    root = tmp_path / "inst"
    (root / "run").mkdir(parents=True)
    (root / "run" / "update_check.json").write_text("not json", encoding="utf-8")
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: "2.0.0")
    st = V.cached_update_status(_Layout(root))
    assert st["latest"] == "2.0.0"
