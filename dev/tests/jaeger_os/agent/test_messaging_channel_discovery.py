"""0.8.1 item 10 — discovery merge (the discord-invisible-to-the-agent bug).

discord/telegram/imessage graduated from ``plugin.yaml`` to ``module.yaml``
at 0.8 M3b (the ``messaging`` module slot). ``list_plugins()`` kept walking
ONLY ``plugin.yaml`` directories, so all three channels silently vanished
from what the agent could see — the model would tell a user "I don't have
discord support" even with the library installed and a token stored.

``list_plugins()`` now merges module-provided messaging channels in
(``kind: "channel"``) alongside manifest-backed plugins (``kind: "plugin"``),
and ``setup_plugin("discord"/"telegram"/"imessage")`` produces a real setup
guide sourced from ``plugins/__init__.py``'s ``_BRIDGE_SPECS`` credential
names instead of erroring "manifest missing or invalid".
"""

from __future__ import annotations

import pathlib
import tempfile

from jaeger_os.agent import tools as agent_tools
from jaeger_os.agent.tools.plugins import list_plugins, setup_plugin
from jaeger_os.core.instance.instance import InstanceLayout


def _rows_by_name() -> dict:
    return {p["name"]: p for p in list_plugins()["plugins"]}


def test_list_plugins_surfaces_all_three_messaging_channels() -> None:
    rows = _rows_by_name()
    for channel in ("discord", "telegram", "imessage"):
        assert channel in rows, f"{channel} missing from list_plugins()"
        row = rows[channel]
        assert row["kind"] == "channel"
        assert row["status"] in (
            "ready", "needs_install", "needs_credentials",
            "needs_install_and_credentials", "unsupported_on_this_platform",
        )
        assert isinstance(row["libraries"], dict)
        assert isinstance(row["platform_ok"], bool)


def test_imessage_is_platform_gated_to_darwin() -> None:
    row = _rows_by_name()["imessage"]
    assert row["platform_required"] == ["darwin"]


def test_manifest_backed_plugins_still_report_kind_plugin() -> None:
    rows = _rows_by_name()
    # homeassistant is a manifest-backed (plugin.yaml) plugin, unaffected
    # by the module-discovery merge — still reported the old way.
    assert rows["homeassistant"]["kind"] == "plugin"


def test_setup_plugin_channel_path_returns_real_steps_not_manifest_error() -> None:
    for channel in ("discord", "telegram", "imessage"):
        res = setup_plugin(channel)
        assert "error" not in res, res
        assert res["kind"] == "channel"
        assert res.get("blocked") in (False, None) or channel != "imessage"
        assert res["steps"], f"{channel}: no steps produced"


def test_setup_plugin_channel_path_names_the_right_credential() -> None:
    """discord's guide must name DISCORD_BOT_TOKEN (not e.g. a generic
    'discord_token' or nothing at all) — the SAME name ``activate_plugin``
    -> ``start_bridge`` -> ``plugin_credential`` reads."""
    res = setup_plugin("discord")
    assert res["env_status"] == {"DISCORD_BOT_TOKEN": "missing"}
    assert any("DISCORD_BOT_TOKEN" in step for step in res["steps"])

    res = setup_plugin("telegram")
    assert res["env_status"] == {"TELEGRAM_BOT_TOKEN": "missing"}

    # imessage has no auth token (platform + AppleScript only) — no
    # required credential, so nothing missing.
    res = setup_plugin("imessage")
    assert res["env_status"] == {}


def test_setup_plugin_channel_path_stores_the_right_credential_names() -> None:
    """End-to-end: set_credential the name setup_plugin told us to, and
    list_plugins must flip that channel's status to reflect it — proving
    the name setup_plugin surfaces is EXACTLY the name the credential
    store / activate_plugin's plugin_credential lookup reads back."""
    from jaeger_os.core.credentials import set_credential

    root = pathlib.Path(tempfile.mkdtemp())
    layout = InstanceLayout(root=root)
    layout.ensure_dirs()

    prev = None
    try:
        prev = agent_tools.get_layout()
    except Exception:  # noqa: BLE001 — none bound yet
        pass
    agent_tools.bind(layout)
    try:
        before = setup_plugin("discord")
        assert before["env_status"]["DISCORD_BOT_TOKEN"] == "missing"
        before_row = _rows_by_name()["discord"]
        assert before_row["status"] == "needs_credentials"

        set_credential(layout, "DISCORD_BOT_TOKEN", "fake-token-value")

        after = setup_plugin("discord")
        assert after["env_status"]["DISCORD_BOT_TOKEN"] == "credential"
        after_row = _rows_by_name()["discord"]
        assert after_row["status"] == "ready"
        assert after_row["env_required"]["DISCORD_BOT_TOKEN"] is True
    finally:
        if prev is not None:
            agent_tools.bind(prev)
