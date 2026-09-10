"""Direct tests for the unified jaeger_ai.features.webui package."""
from jaeger_ai.features.webui import (
    HermesWebUIService,
    hermes_webui_urls,
    ensure_webui_profile_layout,
    profile_display_name,
    HermesWebUIAdapterServer,
    BridgeClient,
)


def test_webui_feature_exports():
    assert HermesWebUIService is not None
    assert callable(hermes_webui_urls)
    assert callable(ensure_webui_profile_layout)
    assert profile_display_name("roundtable") == "Roundtable"
    assert profile_display_name("jaeger") == "Jaeger"
    assert HermesWebUIAdapterServer is not None
    assert BridgeClient is not None


def test_webui_urls_helper():
    urls = hermes_webui_urls(webui_port=8642)
    assert "8642" in urls.container_ui
    assert "8791" in urls.adapter
    assert "8790" in urls.vendor_ui
