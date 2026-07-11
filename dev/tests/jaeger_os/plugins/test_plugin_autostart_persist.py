"""0.8.1 item 8 — activate_plugin persists by default.

An explicit activation (agent tool call, Studio Activate button, /plugins
slash command) is a durable "keep this channel live" decision, not a
one-off for the current process's lifetime: it must survive a restart.
``activate_plugin_inprocess`` now writes the channel into this instance's
``config.plugins.autostart`` on a successful start, using the same
load->mutate->dump_yaml pattern as every other agent-writable setting
(see ``agent/tools/models.py::model_location``).
"""

import pathlib
import tempfile

import jaeger_os.main as m
from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.core.instance.schemas import Config, ModelConfig, dump_yaml, load_yaml


def _fresh_instance() -> InstanceLayout:
    root = pathlib.Path(tempfile.mkdtemp())
    layout = InstanceLayout(root=root)
    cfg = Config(instance_name="test-instance",
                 model=ModelConfig(model_path=pathlib.Path("stub.gguf")))
    dump_yaml(layout.config_path, cfg)
    return layout


def test_activate_plugin_persists_to_autostart(monkeypatch) -> None:
    layout = _fresh_instance()
    cfg = load_yaml(layout.config_path, Config)

    saved_client, saved_layout, saved_cfg = (
        m._pipeline.get("client"), m._pipeline.get("layout"), m._pipeline.get("config"),
    )
    m._pipeline["client"] = object()  # any non-None sentinel — activate_plugin_inprocess
                                       # only checks "is None" before attaching the bridge
    m._pipeline["layout"] = layout
    m._pipeline["config"] = cfg

    def _fake_start_bridge(name, *, layout, handler, llm_lock=None, bus=None):
        return {"started": True, "channel": name}

    monkeypatch.setattr("jaeger_os.plugins.start_bridge", _fake_start_bridge)

    try:
        result = m.activate_plugin_inprocess("telegram")
        assert result["started"] is True

        # in-memory config reflects it immediately
        assert "telegram" in m._pipeline["config"].plugins.autostart

        # AND it made it to disk (the actual persistence contract)
        on_disk = load_yaml(layout.config_path, Config)
        assert on_disk.plugins.autostart == ["telegram"]

        # idempotent: activating again does not duplicate the entry
        result2 = m.activate_plugin_inprocess("telegram")
        assert result2["started"] is True
        on_disk2 = load_yaml(layout.config_path, Config)
        assert on_disk2.plugins.autostart == ["telegram"]
    finally:
        m._pipeline["client"] = saved_client
        m._pipeline["layout"] = saved_layout
        m._pipeline["config"] = saved_cfg
