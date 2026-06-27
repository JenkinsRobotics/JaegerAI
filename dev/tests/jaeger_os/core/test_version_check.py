"""Version parsing + latest-release comparison (network-free parts)."""

from __future__ import annotations

from jaeger_os.core import version_check as V


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
    import jaeger_os
    # newer available
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: "99.0.0")
    st = V.update_status()
    assert st["current"] == jaeger_os.__version__
    assert st["latest"] == "99.0.0"
    assert st["available"] is True
    # same version → not available
    monkeypatch.setattr(V, "latest_version", lambda *a, **k: jaeger_os.__version__)
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
