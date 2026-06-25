"""Plugin auto-start option + the shared in-process activation helper.

Auto-start is opt-in (config.plugins.autostart) and best-effort: it never
delays or fails boot, and a missing credential is just skipped.
"""

from types import SimpleNamespace

from jaeger_os.core.instance.schemas import PluginsConfig


def test_plugins_autostart_defaults_empty() -> None:
    assert PluginsConfig().autostart == []


def test_plugins_autostart_parses_names() -> None:
    assert PluginsConfig(autostart=["telegram"]).autostart == ["telegram"]


def test_activate_inprocess_without_client_is_honest() -> None:
    import jaeger_os.main as m
    saved = m._pipeline.get("client")
    m._pipeline["client"] = None
    try:
        r = m.activate_plugin_inprocess("telegram")
    finally:
        m._pipeline["client"] = saved
    assert r["started"] is False and "no agent" in r["error"]


def test_autostart_is_noop_when_empty_or_absent() -> None:
    import jaeger_os.main as m
    # empty list → returns immediately, spawns nothing, never raises
    m.autostart_plugins(SimpleNamespace(plugins=SimpleNamespace(autostart=[])))
    # no plugins attr at all → also a clean no-op
    m.autostart_plugins(SimpleNamespace())
