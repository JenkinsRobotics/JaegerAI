"""In-process plugin activation — plugins reference the agent INSTANCE.

The Lilith/Jarvis episode: the agent saved a token to the instance credential
store, but the bridge read it from os.environ — they never met, and there was
no way to start the bridge in the agent's own process. These cover the fix:
credentials resolve instance-folder-first, and start_bridge surfaces the real
state (no confabulated reasons).
"""

import pathlib
import tempfile

from jaeger_os.core import credentials as creds
from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.plugins import plugin_credential, start_bridge


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


def test_start_bridge_unknown_plugin_is_honest() -> None:
    r = start_bridge("nope", layout=_layout(), handler=lambda *a, **k: "")
    assert r["started"] is False and "no in-process bridge" in r["error"]


def test_start_bridge_telegram_reports_missing_credential(monkeypatch) -> None:
    # No token in the store and none in env → a precise, actionable error
    # (ask the user + set_credential), NOT a confabulated "module import error".
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    r = start_bridge("telegram", layout=_layout(), handler=lambda *a, **k: "")
    assert r["started"] is False
    assert "TELEGRAM_BOT_TOKEN" in r["error"] and "set_credential" in r["error"]


def test_telegram_bridge_takes_passed_token_not_env(monkeypatch) -> None:
    # The bridge no longer reaches into os.environ when handed a token.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    from jaeger_os.plugins.telegram.bridge import TelegramBridge
    b = TelegramBridge(lambda *a, **k: "", token="passed-token",
                       allowed_chats={123})
    assert b._token == "passed-token"
    assert b._allowed == {123}
