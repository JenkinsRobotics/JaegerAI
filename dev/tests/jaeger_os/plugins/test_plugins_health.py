"""Plugin health — every plugin is sound and the agent can execute the plugin
tools end to end (short of the live external connection, which needs real
tokens / sockets).

This is the "are all the plugins actually working?" check: manifests parse,
every declared library imports, list_plugins / setup_plugin run for every
plugin, and the plugin tools (list_plugins, setup_plugin, activate_plugin,
send_message) are all registered on the agent.
"""

import pathlib

import yaml

import jaeger_os.plugins as _plugins_pkg
from jaeger_os.agent.tools.plugins import list_plugins, setup_plugin

PLUGINS_DIR = pathlib.Path(_plugins_pkg.__file__).parent


def _plugin_dirs() -> list[pathlib.Path]:
    return sorted(d for d in PLUGINS_DIR.iterdir()
                  if d.is_dir() and (d / "plugin.yaml").exists())


def test_plugins_exist() -> None:
    assert _plugin_dirs(), "no plugins found under jaeger_os/plugins/"


def test_every_plugin_has_a_valid_manifest() -> None:
    for d in _plugin_dirs():
        doc = yaml.safe_load((d / "plugin.yaml").read_text(encoding="utf-8")) or {}
        assert doc.get("name"), f"{d.name}: manifest missing 'name'"
        assert "requires" in doc, f"{d.name}: manifest missing 'requires'"


def test_list_plugins_covers_every_folder() -> None:
    reported = {p.get("name") for p in list_plugins().get("plugins", [])}
    for d in _plugin_dirs():
        assert d.name in reported, f"{d.name} not reported by list_plugins()"


def test_every_declared_library_imports() -> None:
    """The load-bearing health check: a plugin whose declared library can't be
    imported is broken/unusable. Every reported library must resolve True."""
    broken = [
        f"{p.get('name')}:{lib}"
        for p in list_plugins().get("plugins", [])
        for lib, ok in (p.get("libraries") or {}).items()
        if not ok
    ]
    assert not broken, f"plugins with un-importable libraries: {broken}"


def test_setup_plugin_runs_for_every_plugin() -> None:
    for d in _plugin_dirs():
        res = setup_plugin(d.name)
        # Either it's blocked (e.g. wrong platform) or it returns actionable
        # steps with no hard error — never an exception or unknown-plugin error.
        assert res.get("blocked") or "error" not in res, f"{d.name}: {res}"
        assert res.get("blocked") or res.get("steps") is not None, f"{d.name}: {res}"


def test_setup_plugin_works_with_a_bound_layout() -> None:
    """Regression: ``_credential_status`` did ``from .. import credentials``
    (jaeger_os.agent.credentials — doesn't exist). It was masked whenever NO
    layout was bound (the function returns early), so it only blew up once a
    layout was bound — i.e. in the real running agent. Deterministic guard:
    bind a layout, then setup_plugin for a credential-requiring plugin."""
    import pathlib
    import tempfile

    from jaeger_os.agent import tools as agent_tools
    from jaeger_os.core.instance.instance import InstanceLayout

    try:
        prev = agent_tools.get_layout()
    except Exception:  # noqa: BLE001 — none bound yet
        prev = None
    agent_tools.bind(InstanceLayout(root=pathlib.Path(tempfile.mkdtemp())))
    try:
        res = setup_plugin("telegram")  # telegram declares env_required creds
        assert "error" not in res, res          # no ImportError surfaced
        assert res.get("steps") is not None, res
    finally:
        if prev is not None:
            agent_tools.bind(prev)


def test_agent_can_execute_plugin_tools() -> None:
    """All four plugin tools must be registered, or the agent can't drive
    plugins at all (the Jarvis failure was reaching for a tool that didn't
    exist)."""
    from jaeger_os.agent.schemas import tool_registry as R
    import jaeger_os.main as m
    m._register_builtins(object())
    names = {t.name for t in R.get_tools()}
    for tool in ("list_plugins", "setup_plugin", "activate_plugin", "send_message"):
        assert tool in names, f"{tool} not registered — agent cannot execute plugins"
