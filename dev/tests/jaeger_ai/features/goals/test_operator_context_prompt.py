"""operator.toml → system prompt wiring.

``OperatorConfig.to_prompt_context`` was defined but never called before the
goals feature. These tests pin the new wiring: the ``operator_context``
prompt fragment renders the operator block, and ``[[operator.projects]]``
tables surface as an Active projects list.
"""

from jaeger_ai.core.instance.operator_config import OperatorConfig
from jaeger_ai.core.prompt_documents import (
    OPERATOR_CONTEXT_FRAGMENT,
    load_operator_context,
    register_context_documents,
)


def test_to_prompt_context_includes_projects() -> None:
    cfg = OperatorConfig(
        business_name="Jenkins Robotics",
        nas_path="/Volumes/MyNAS",
        projects=(
            {"name": "Robot Arm v2", "build_cmd": "swift test",
             "tool_bundle": "robotics.build"},
            {"name": "Episode 12"},
        ),
        custom_context="Prefer concise answers.",
    )
    text = cfg.to_prompt_context()
    assert "Business: Jenkins Robotics" in text
    assert "NAS: /Volumes/MyNAS" in text
    assert "Active projects:" in text
    assert "- Robot Arm v2 (tools: robotics.build) build: swift test" in text
    assert "- Episode 12" in text
    assert "Additional context: Prefer concise answers." in text


def test_to_prompt_context_empty_by_default() -> None:
    assert OperatorConfig().to_prompt_context() == ""


def test_from_dict_parses_projects_tables() -> None:
    cfg = OperatorConfig.from_dict({
        "projects": [
            {"name": "P1", "tool_bundle": "goals"},
            "plain-string-project",
        ],
    })
    assert cfg.projects[0]["name"] == "P1"
    # Bare strings normalise to {"name": ...}.
    assert cfg.projects[1] == {"name": "plain-string-project"}


def test_load_operator_context_renders_block(monkeypatch, tmp_path) -> None:
    toml = tmp_path / "operator.toml"
    toml.write_text(
        '[operator]\nname = "Alex"\n'
        '[[operator.projects]]\nname = "Robot Arm"\ntool_bundle = "robotics.build"\n',
        encoding="utf-8",
    )
    # prompt_documents imports load_operator_config inside the function;
    # patch it on its source module so the lazy import picks up the stub.
    import jaeger_ai.core.instance.operator_config as oc
    import tomllib
    data = tomllib.loads(toml.read_text())["operator"]
    monkeypatch.setattr(
        oc, "load_operator_config",
        lambda *a, **k: OperatorConfig.from_dict(data),
    )
    block = load_operator_context()
    assert block.startswith("[OPERATOR CONTEXT]")
    assert "Active projects:" in block
    assert "- Robot Arm (tools: robotics.build)" in block


def test_register_context_documents_adds_operator_fragment() -> None:
    try:
        from jaeger_agent.prompts import assemble
    except Exception:  # noqa: BLE001 — assembler not importable in this env
        return
    assemble.PROMPT_FRAGMENTS[:] = [
        f for f in assemble.PROMPT_FRAGMENTS
        if f.name != OPERATOR_CONTEXT_FRAGMENT
    ]
    assert register_context_documents() is True
    names = [f.name for f in assemble.PROMPT_FRAGMENTS]
    assert OPERATOR_CONTEXT_FRAGMENT in names
    # Idempotent: a second registration must not duplicate the fragment.
    assert register_context_documents() is True
    names = [f.name for f in assemble.PROMPT_FRAGMENTS]
    assert names.count(OPERATOR_CONTEXT_FRAGMENT) == 1
