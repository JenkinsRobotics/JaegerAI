"""Canonical runtime truth: product default, inventories, vision labels."""

from __future__ import annotations

from pathlib import Path

from jaeger_ai.contract.frameworks import (
    PRODUCT_DEFAULT_PROFILE,
    PRODUCT_DEFAULT_RUNTIME,
    canonical_runtime,
    product_default_profile,
)
from jaeger_ai.core.runtime.truth import (
    _active_model,
    capability_prompt_block,
    capability_snapshot,
    framework_inventory,
    webui_model_catalog,
)
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml, load_yaml


def test_product_default_is_jaeger():
    assert PRODUCT_DEFAULT_RUNTIME == "jaeger"
    assert PRODUCT_DEFAULT_PROFILE == "jaeger"
    assert product_default_profile() == "jaeger"
    assert canonical_runtime("default") == "hermes"
    assert canonical_runtime("jaeger") == "jaeger"


def test_framework_inventory_marks_jaeger_product_default():
    rows = framework_inventory(probe=lambda name: name == "jaeger")
    by_id = {r["runtime_id"]: r for r in rows}
    assert by_id["jaeger"]["is_product_default"] is True
    assert by_id["jaeger"]["available"] is True
    assert by_id["hermes"]["is_product_default"] is False
    assert by_id["hermes"]["available"] is False
    assert by_id["openclaw"]["available"] is False


def test_capability_snapshot_does_not_claim_unconfigured_cloud():
    snap = capability_snapshot()
    providers = ((snap.get("providers") or {}).get("inventory") or {}).get("providers") or []
    by_id = {p["id"]: p for p in providers}
    if "anthropic" in by_id:
        assert by_id["anthropic"]["configured"] is False
        assert by_id["anthropic"]["reachable"] is False
        assert by_id["anthropic"]["models"] == []
    assert "entity_id" in (snap.get("identity") or {})


def test_product_default_model_is_kimi():
    from jaeger_ai.contract.frameworks import DEFAULT_AGENT_MODEL
    assert DEFAULT_AGENT_MODEL == "kimi-k2.7-code:cloud"


def test_prompt_block_carries_the_real_tool_list_for_tool_less_turns():
    """``DIRECT_RESPONSE`` runs with an empty tool allowlist by design, so it
    cannot call ``list_tools``/``help_me`` to answer "what tools do you have".

    Live defect (audit, 2026-09-22): with no tool list in ``runtime_truth``,
    that question (and "open youtube for me", which read as informational
    too) landed on a tool-less turn with zero grounding. The model guessed
    from generic assumptions and repeatedly, confidently told the operator
    it had no web/browser tool at all — a capability this instance actually
    has (``web_search``, ``open_on_host``).
    """
    block = capability_prompt_block(None)

    assert "web_search" in block
    assert "open_on_host" in block
    assert "do not claim a narrower toolset" in block


def test_webui_catalog_shape():
    cat = webui_model_catalog()
    assert "groups" in cat
    assert "default_model" in cat
    assert cat.get("source") == "jaeger.runtime.truth"


def test_composer_has_no_hardcoded_orphan_models():
    html = Path("jaeger_ai/features/webui/static/index.html").read_text(encoding="utf-8")
    assert "openai/gpt-4o" not in html
    assert "anthropic/claude-sonnet" not in html
    assert 'optgroup label="Other"' not in html


def test_webui_catalog_is_provider_and_model_only():
    cat = webui_model_catalog()
    for group in cat.get("groups") or []:
        models = group.get("models") or []
        assert models, f"{group.get('provider')} must not be an empty provider row"
        assert group.get("provider")
        assert group.get("provider_id")
        for model in models:
            label = str(model.get("label") or "")
            name = str(model.get("name") or "")
            assert label == name
            assert "REACT" not in label.upper()
            assert "certified" not in label.lower()
            assert "FAIL" not in label
            assert "[" not in label
            assert model.get("certified_badge") in (None, "")


def _layout(tmp_path: Path) -> InstanceLayout:
    layout = InstanceLayout(root=tmp_path / "instance")
    layout.root.mkdir(parents=True)
    layout.ensure_dirs()
    dump_yaml(layout.config_path, Config(
        instance_name="test", model=ModelConfig(model_path="/dev/null")))
    return layout


def test_active_model_reports_the_configured_external_model(tmp_path: Path):
    """``active_model`` must be config.yaml's own value, not a certification
    lookup with a hardcoded fallback.

    Live defect (audit, 2026-09-22): config.yaml said ``glm-5.3-flash:cloud``
    while the "authoritative; do not invent" prompt block told the model
    ``active_model=kimi-k2.7-code:cloud`` — the hardcoded fallback
    ``select_production_model()`` returns when no certification matrix file
    exists. The agent repeated that wrong name to the operator as fact.
    """
    layout = _layout(tmp_path)
    config = load_yaml(layout.config_path, Config)
    config.external_model.enabled = True
    config.external_model.provider = "ollama"
    config.external_model.model = "glm-5.3-flash:cloud"
    dump_yaml(layout.config_path, config)
    # No certification matrix file exists in this fresh instance — that must
    # not matter once a live external model is configured.

    assert _active_model(layout.root) == {"provider": "ollama", "model": "glm-5.3-flash:cloud"}


def test_active_model_falls_back_to_certification_when_local_only(tmp_path: Path):
    """With no external model configured (local llama.cpp mode), the
    certification matrix's production pick is still the right fallback."""
    layout = _layout(tmp_path)
    assert load_yaml(layout.config_path, Config).external_model.enabled is False

    from jaeger_ai.core.instance.provider_certification import CERT_FILENAME

    (layout.root / CERT_FILENAME).write_text(
        '{"assignments": {"REACT": {"provider": "ollama", "model": "committee-pick:cloud"}}}',
        encoding="utf-8",
    )

    assert _active_model(layout.root) == {"provider": "ollama", "model": "committee-pick:cloud"}


def test_gateway_attachments_do_not_escape_via_store(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "gw.sqlite3")
    store.ensure_session("sess-1", title="t", profile="jaeger")
    row = store.add_attachment("sess-1", {
        "original_filename": "note.txt",
        "stored_filename": "aa_note.txt",
        "safe_path": str(tmp_path / "note.txt"),
        "mime_type": "text/plain",
        "size_bytes": 4,
        "sha256": "abcd",
        "provenance": "remote_upload",
    })
    listed = store.list_attachments("sess-1")
    assert listed[0]["attachment_id"] == row["attachment_id"]
    assert listed[0]["original_filename"] == "note.txt"
    assert listed[0]["provenance"] == "remote_upload"
