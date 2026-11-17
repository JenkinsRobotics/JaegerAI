"""In-process plugin activation — plugins reference the agent INSTANCE.

The Lilith/Jarvis episode: the agent saved a token to the instance credential
store, but the bridge read it from os.environ — they never met, and there was
no way to start the bridge in the agent's own process. These cover the fix:
credentials resolve instance-folder-first, and start_bridge surfaces the real
state (no confabulated reasons).
"""

import pathlib
import tempfile

from jaeger_agent.core import credentials as creds
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.plugins import plugin_credential


def _layout() -> InstanceLayout:
    return InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))


def test_credential_resolves_instance_store_first() -> None:
    layout = _layout()
    creds.set_credential(layout, "TELEGRAM_BOT_TOKEN", "store-token")
    assert plugin_credential(layout, "TELEGRAM_BOT_TOKEN") == "store-token"


def test_credential_falls_back_to_env(monkeypatch) -> None:
    layout = _layout()  # empty store
    monkeypatch.setenv("SOME_PLUGIN_KEY", "env-token")
    assert plugin_credential(layout, "SOME_PLUGIN_KEY") == "env-token"


def test_credential_empty_when_neither(monkeypatch) -> None:
    monkeypatch.delenv("NOPE_KEY", raising=False)
    assert plugin_credential(_layout(), "NOPE_KEY") == ""














def test_uppercase_saved_credential_reads_as_configured(tmp_path) -> None:
    """Regression: a credential saved UPPERCASE (HASS_TOKEN — as
    set_credential and the manifest use it) read as 'needs_credentials' because
    the status check lowercased only the lookup side, not the stored name. So a
    saved-and-working token still showed 'not configured' after a restart.
    Case-insensitive now.

    Uses ``homeassistant`` (0.8 M3b: telegram graduated to a
    module.yaml-only messaging module — it no longer has a plugin.yaml
    for ``setup_plugin`` to read; homeassistant is still a real plugin
    with an env-gated credential, same shape this regression needs)."""
    from jaeger_agent import tools as agent_tools
    from jaeger_agent.tools.plugins import setup_plugin
    from jaeger_agent.core import credentials as creds

    layout = InstanceLayout(root=tmp_path)
    creds.set_credential(layout, "HASS_TOKEN", "tok:val")
    try:
        prev = agent_tools.get_layout()
    except Exception:  # noqa: BLE001
        prev = None
    agent_tools.bind(layout)
    try:
        steps = " ".join(setup_plugin("homeassistant").get("steps", []))
        assert "Provide credential `HASS_TOKEN`" not in steps, steps
    finally:
        if prev is not None:
            agent_tools.bind(prev)
