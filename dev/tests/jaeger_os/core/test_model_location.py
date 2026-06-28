"""model_location tool — agent-managed custom GGUF scan directories.

The agent's writes are sandboxed to `<instance>/skills/`; it cannot edit
core files. The agent-safe way to extend the model scan set is therefore
*config + a tool*: `model_location` registers a directory into
`model.extra_gguf_dirs`, and `discover_local_gguf` reads it. This is the
template for "let the agent add a feature without editing core code".
"""

from __future__ import annotations

import pytest

from jaeger_os.core.models import model_discovery
from jaeger_os.agent import tools
from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.core.safety.permissions import (
    AllowAllProvider,
    PermissionPolicy,
    use_policy,
)
from jaeger_os.core.instance.schemas import Config, ModelConfig, dump_yaml


@pytest.fixture()
def bound(tmp_path, monkeypatch):
    """A bound instance with a live config in `_pipeline`."""
    from jaeger_os.main import _pipeline

    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    cfg = Config(instance_name="t",
                 model=ModelConfig(model_path="/tmp/x.gguf"))
    dump_yaml(layout.config_path, cfg)
    monkeypatch.setitem(_pipeline, "config", cfg)
    monkeypatch.setitem(_pipeline, "layout", layout)
    return layout, cfg


def _call(action: str, path: str = "") -> dict:
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        return tools.model_location(action=action, path=path)


def test_list_is_empty_on_a_fresh_config(bound):
    out = _call("list")
    assert out["ok"] is True
    assert out["extra_gguf_dirs"] == []


def test_add_registers_an_existing_directory(bound, tmp_path):
    target = tmp_path / "my_models"
    target.mkdir()
    out = _call("add", str(target))
    assert out["ok"] is True
    assert str(target) in out["extra_gguf_dirs"]


def test_add_rejects_a_non_directory(bound, tmp_path):
    out = _call("add", str(tmp_path / "does_not_exist"))
    assert out["ok"] is False
    assert "not a directory" in out["error"]


def test_add_is_idempotent(bound, tmp_path):
    target = tmp_path / "models2"
    target.mkdir()
    _call("add", str(target))
    out = _call("add", str(target))
    assert out["ok"] is True
    assert out["extra_gguf_dirs"].count(str(target)) == 1


def test_remove_unregisters(bound, tmp_path):
    target = tmp_path / "models3"
    target.mkdir()
    _call("add", str(target))
    out = _call("remove", str(target))
    assert out["ok"] is True
    assert str(target) not in out["extra_gguf_dirs"]


def test_remove_unknown_path_errors(bound, tmp_path):
    out = _call("remove", str(tmp_path / "never_added"))
    assert out["ok"] is False


def test_unknown_action_errors(bound):
    out = _call("frobnicate")
    assert out["ok"] is False
    assert "unknown action" in out["error"]


def test_add_persists_to_the_config_file(bound, tmp_path):
    """The registration must survive a restart — it is written to
    config.yaml, not just held in memory."""
    layout, _ = bound
    target = tmp_path / "persisted"
    target.mkdir()
    _call("add", str(target))
    reloaded = Config.model_validate(
        __import__("yaml").safe_load(layout.config_path.read_text()))
    assert str(target) in reloaded.model.extra_gguf_dirs


def test_discover_local_gguf_picks_up_a_registered_dir(bound, tmp_path):
    """End to end: a .gguf in a registered custom directory shows up in
    discovery tagged 'custom'."""
    custom = tmp_path / "stash"
    custom.mkdir()
    (custom / "fake-model.gguf").write_bytes(b"")   # an empty .gguf file
    _call("add", str(custom))

    found = model_discovery.discover_local_gguf()
    paths = [m["path"] for m in found]
    assert str(custom / "fake-model.gguf") in paths
    custom_entry = next(m for m in found
                        if m["path"] == str(custom / "fake-model.gguf"))
    assert custom_entry["source"] == "custom"


# ── download progress line (urllib fallback) ───────────────────────


def test_progress_line_has_bar_pct_speed_and_eta() -> None:
    from jaeger_os.core.models.model_resolver import _progress_line
    line = _progress_line("gemma", done=500 * 1024 * 1024,
                          total=1000 * 1024 * 1024, elapsed=10.0)
    assert "50.0%" in line                       # halfway
    assert "[" in line and "]" in line           # the bar
    assert "MB/s" in line and "ETA" in line       # speed + eta
    assert _progress_line("g", 1000, 1000, 1.0).count("100.0%") == 1   # full
    # zero/total guards don't divide-by-zero
    assert "0.0%" in _progress_line("g", 0, 0, 0.0)
