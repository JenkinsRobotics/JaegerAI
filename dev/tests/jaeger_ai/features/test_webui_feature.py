"""Direct tests for the unified jaeger_ai.features.webui package."""
from pathlib import Path

from jaeger_ai.contract.frameworks import FRAMEWORKS
from jaeger_ai.features.webui import (
    WebUIService,
    webui_urls,
    ensure_webui_profile_layout,
    profile_display_name,
    HermesWebUIAdapterServer,
    BridgeClient,
)
from jaeger_ai.features.webui.service.service import (
    parse_webui_shell,
    webui_identity_ok,
)

_REPO = Path(__file__).resolve().parents[4]
_INDEX = _REPO / "jaeger_ai" / "features" / "webui" / "static" / "index.html"


def test_webui_feature_exports():
    assert WebUIService is not None
    assert callable(webui_urls)
    assert callable(ensure_webui_profile_layout)
    # Asserted against the contract, not retyped: these two assertions said
    # "Jaeger" for weeks after the shipped name became "Jaeger AI".
    for f in FRAMEWORKS:
        assert profile_display_name(f.runtime) == f.display_name
    assert HermesWebUIAdapterServer is not None
    assert BridgeClient is not None


def test_webui_urls_helper():
    urls = webui_urls(webui_port=8642)
    assert "8642" in urls.web_ui
    assert "8791" in urls.adapter


def test_bundle_version_stamp_has_no_cache_suffix():
    html = _INDEX.read_text(encoding="utf-8")
    assert "window.__HERMES_WEBUI_BUNDLE_VERSION__='__WEBUI_VERSION__';" in html
    assert "window.__HERMES_WEBUI_BUNDLE_VERSION__='__WEBUI_VERSION__." not in html


def test_identity_ok_when_bundle_matches_settings():
    html = (
        "<title>Jaeger</title>"
        "<script>window.__HERMES_WEBUI_BUNDLE_VERSION__='exp-v0.52.264-13-g9044bddf';</script>"
    )
    shell = parse_webui_shell(html)
    result = webui_identity_ok(shell, {"webui_version": "exp-v0.52.264-13-g9044bddf"})
    assert result["ok"] is True
    assert result["skew"] is False


def test_identity_skew_when_bundle_has_cache_suffix():
    html = (
        "<title>Jaeger</title>"
        "<script>window.__HERMES_WEBUI_BUNDLE_VERSION__="
        "'exp-v0.52.264-13-g9044bddf.jaegerpd4';</script>"
    )
    result = webui_identity_ok(
        parse_webui_shell(html),
        {"webui_version": "exp-v0.52.264-13-g9044bddf"},
    )
    assert result["ok"] is False
    assert result["skew"] is True
    assert "version skew" in (result["error"] or "")
