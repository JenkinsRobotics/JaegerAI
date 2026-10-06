"""One identity authority.

``EntityIdentity`` (``entity_identity.json``) is who Jaeger is. ``identity.yaml``
and the prompt header are projections of it. A model, a provider switch, a
session, an outside caller or a background turn cannot change it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction
from jaeger_ai.core.entity.identity import (
    EntityIdentity,
    IDENTITY_FILE_NAME,
    rename_entity,
    resolve_entity_identity,
)


def test_the_entity_id_survives_a_rename_and_every_reload(tmp_path):
    first = resolve_entity_identity(tmp_path)
    renamed = rename_entity(tmp_path, "Erin")

    assert renamed.entity_id == first.entity_id
    assert renamed.display_name == "Erin"
    assert resolve_entity_identity(tmp_path).entity_id == first.entity_id
    assert resolve_entity_identity(tmp_path).display_name == "Erin"
    assert EntityIdentity.load_from_file(tmp_path / IDENTITY_FILE_NAME).display_name == "Erin"


def test_a_rename_to_the_same_name_changes_nothing_and_a_blank_name_is_refused(tmp_path):
    first = resolve_entity_identity(tmp_path)
    assert rename_entity(tmp_path, first.display_name) == first
    with pytest.raises(ValueError):
        rename_entity(tmp_path, "   ")
    assert resolve_entity_identity(tmp_path) == first


def test_resolving_with_other_defaults_never_mints_a_second_identity(tmp_path):
    """A new model, instance label or default name is not a new Jaeger."""
    first = resolve_entity_identity(tmp_path, default_name="Jaeger", instance_name="default")
    again = resolve_entity_identity(tmp_path, default_name="Someone Else", instance_name="other")
    assert again.entity_id == first.entity_id and again.display_name == first.display_name


@pytest.mark.parametrize("tool", ["set_name", "update_soul", "adjust_trait"])
@pytest.mark.parametrize("actor", ["mcp", "a2a", "mcp:codex", "agent:jaeger", "guest", "helper:worker", ""])
def test_identity_tools_are_denied_to_everyone_but_the_owner(tool, actor):
    decision = PolicyKernel().evaluate(ProposedAction(tool_name=tool, arguments={}, actor=actor))
    assert decision.decision == AuthorityDecisionType.DENY
    assert decision.policy_name in {"identity_authority", "identity_required"}


@pytest.mark.parametrize("tool", ["set_name", "update_soul", "adjust_trait"])
@pytest.mark.parametrize("actor", ["owner:cli", "owner:webui", "owner:menubar", "human:operator"])
def test_an_authenticated_owner_turn_is_not_denied_by_the_identity_rule(tool, actor):
    decision = PolicyKernel().evaluate(ProposedAction(tool_name=tool, arguments={}, actor=actor))
    assert decision.policy_name != "identity_authority"


def test_set_name_updates_the_authority_first_and_projects_identity_yaml(tmp_path, monkeypatch):
    from jaeger_ai.core.instance.schemas import Identity, dump_yaml, load_yaml
    from jaeger_agent.tools import identity_tools

    memory = tmp_path / "memory"
    memory.mkdir()
    yaml_path = tmp_path / "identity.yaml"
    dump_yaml(yaml_path, Identity(name="Jaeger", role="assistant", personality="steady"))
    anchor = resolve_entity_identity(memory)
    layout = SimpleNamespace(identity_path=yaml_path, memory_dir=memory, root=tmp_path)
    monkeypatch.setattr(identity_tools, "_require_layout", lambda: layout)
    monkeypatch.setattr(identity_tools, "_apply_identity_change", lambda: None)

    result = identity_tools.set_name("Erin")

    assert result["ok"] is True
    assert resolve_entity_identity(memory).display_name == "Erin"       # the authority
    assert resolve_entity_identity(memory).entity_id == anchor.entity_id
    assert load_yaml(yaml_path, Identity).name == "Erin"                 # the projection
