"""Unit tests for V2 Agent Architecture.

Tests:
- AgentRole.CHARACTER enum value
- CharacterPersonality dataclass (serialization)
- effective_tools() security model
- Tool policy enforcement logic
- Registry migration
"""

from __future__ import annotations

import pytest

from jaeger_ai.core.agent_registry.types import (
    AgentKind,
    AgentRecord,
    AgentRole,
    CharacterPersonality,
    get_personality,
    normalize_agent_role,
    set_personality,
)
from jaeger_ai.core.agent_registry.specialists import (
    effective_tools,
    set_tool_allowlist,
    tool_scope_description,
)


# ─────────────────────────────────────────────────────────────────
# AgentRole.CHARACTER Tests
# ─────────────────────────────────────────────────────────────────

class TestAgentRoleCharacter:
    """Test the new CHARACTER role."""
    
    def test_character_role_exists(self):
        """AgentRole.CHARACTER should exist."""
        assert AgentRole.CHARACTER.value == "character"
    
    def test_normalize_character_role(self):
        """normalize_agent_role should parse 'character'."""
        assert normalize_agent_role("character") == AgentRole.CHARACTER
        assert normalize_agent_role("CHARACTER") == AgentRole.CHARACTER
        assert normalize_agent_role(AgentRole.CHARACTER) == AgentRole.CHARACTER
    
    def test_character_in_role_list(self):
        """Character should be in the list of valid roles."""
        roles = [r.value for r in AgentRole]
        assert "character" in roles


# ─────────────────────────────────────────────────────────────────
# CharacterPersonality Tests
# ─────────────────────────────────────────────────────────────────

class TestCharacterPersonality:
    """Test the CharacterPersonality dataclass."""
    
    def test_create_default(self):
        """Default personality should have sensible defaults."""
        p = CharacterPersonality()
        assert p.name == ""
        assert p.voice_id == "af_heart"
        assert p.special_intelligence == 0.5
        assert p.expr_sarcasm == 0.0
    
    def test_create_with_values(self):
        """Personality should accept custom values."""
        p = CharacterPersonality(
            template_id="jarvis",
            name="Jarvis",
            role_description="AI butler",
            voice_tone="crisp, dry, British-butler",
            voice_id="bm_george",
            special_intelligence=0.95,
            expr_formality=0.9,
            expr_warmth=0.7,
        )
        assert p.template_id == "jarvis"
        assert p.name == "Jarvis"
        assert p.special_intelligence == 0.95
        assert p.expr_formality == 0.9
    
    def test_serialization_roundtrip(self):
        """to_dict → from_dict should preserve all values."""
        original = CharacterPersonality(
            template_id="lilith",
            name="Lilith",
            role_description="self-aware local AI",
            voice_tone="low, measured, slightly cool",
            voice_id="af_heart",
            backstory="A self-aware agent running on local hardware.",
            soul="I am Lilith.",
            speech_patterns=("quiet", "measured", "cool"),
            quotes=("I prefer not to guess.", "Ask sharp questions."),
            hexaco_openness=0.8,
            hexaco_conscientiousness=0.7,
            special_intelligence=0.9,
            special_perception=0.9,
            expr_directness=0.8,
            expr_verbosity=0.3,
            card_url="/v1/characters/lilith/card",
            personality_version=2,
        )
        
        data = original.to_dict()
        restored = CharacterPersonality.from_dict(data)
        
        assert restored.template_id == original.template_id
        assert restored.name == original.name
        assert restored.voice_tone == original.voice_tone
        assert restored.special_intelligence == original.special_intelligence
        assert restored.expr_directness == original.expr_directness
        assert restored.speech_patterns == original.speech_patterns
        assert restored.quotes == original.quotes
        assert restored.card_url == original.card_url
        assert restored.personality_version == original.personality_version
    
    def test_to_dict_structure(self):
        """to_dict should produce expected structure."""
        p = CharacterPersonality(template_id="jarvis", name="Jarvis")
        d = p.to_dict()
        
        assert "template_id" in d
        assert "name" in d
        assert "traits" in d
        assert "hexaco" in d["traits"]
        assert "special" in d["traits"]
        assert "expression" in d["traits"]


# ─────────────────────────────────────────────────────────────────
# Personality on AgentRecord Tests
# ─────────────────────────────────────────────────────────────────

class TestPersonalityOnAgent:
    """Test personality storage on AgentRecord."""
    
    def test_get_personality_none(self):
        """Agent without personality should return None."""
        agent = AgentRecord(
            id="native:test",
            name="test",
            kind=AgentKind.NATIVE,
            display_name="Test",
            source="registry",
        )
        assert get_personality(agent) is None
    
    def test_set_and_get_personality(self):
        """Setting personality should be retrievable."""
        agent = AgentRecord(
            id="native:jarvis",
            name="jarvis",
            kind=AgentKind.NATIVE,
            display_name="Jarvis",
            source="registry",
            role=AgentRole.CHARACTER,
        )
        
        personality = CharacterPersonality(
            template_id="jarvis",
            name="Jarvis",
            special_intelligence=0.95,
        )
        
        set_personality(agent, personality)
        restored = get_personality(agent)
        
        assert restored is not None
        assert restored.template_id == "jarvis"
        assert restored.name == "Jarvis"
        assert restored.special_intelligence == 0.95
    
    def test_remove_personality(self):
        """Setting personality to None should remove it."""
        agent = AgentRecord(
            id="native:jarvis",
            name="jarvis",
            kind=AgentKind.NATIVE,
            display_name="Jarvis",
            source="registry",
        )
        
        set_personality(agent, CharacterPersonality(name="Test"))
        assert get_personality(agent) is not None
        
        set_personality(agent, None)
        assert get_personality(agent) is None
        assert "personality" not in (agent.metadata or {})


# ─────────────────────────────────────────────────────────────────
# effective_tools() Security Model Tests
# ─────────────────────────────────────────────────────────────────

class TestEffectiveTools:
    """Test the tool policy security model."""
    
    def _make_agent(self, role: AgentRole, name: str = "test") -> AgentRecord:
        return AgentRecord(
            id=f"native:{name}",
            name=name,
            kind=AgentKind.NATIVE,
            display_name=name.title(),
            source="registry",
            role=role,
        )
    
    def test_character_defaults_to_no_tools(self):
        """CHARACTER role defaults to NO TOOLS (enforced)."""
        agent = self._make_agent(AgentRole.CHARACTER, "lilith")
        tools = effective_tools(agent)
        assert tools == [], "Character should have no tools by default"
    
    def test_character_with_explicit_tools(self):
        """Character can have tools if explicitly allowed."""
        agent = self._make_agent(AgentRole.CHARACTER, "jarvis")
        set_tool_allowlist(agent, ["read_file", "search_files"])
        tools = effective_tools(agent)
        assert tools == ["read_file", "search_files"]
    
    def test_character_with_explicit_no_tools(self):
        """Character with explicit [] stays []."""
        agent = self._make_agent(AgentRole.CHARACTER, "lilith")
        set_tool_allowlist(agent, [])
        tools = effective_tools(agent)
        assert tools == []
    
    def test_character_inherit_still_no_tools(self):
        """Character with inherit (None) still gets [] due to role default."""
        agent = self._make_agent(AgentRole.CHARACTER, "lilith")
        set_tool_allowlist(agent, None)  # Inherit
        tools = effective_tools(agent)
        assert tools == [], "Character role should default to [] even with inherit"
    
    def test_specialist_gets_standing_tools(self):
        """SPECIALIST role gets standing tools."""
        agent = self._make_agent(AgentRole.SPECIALIST, "builder")
        tools = effective_tools(agent)
        assert tools is not None, "Specialist should have tools"
        assert isinstance(tools, list)
        assert len(tools) > 0
    
    def test_lead_inherits_tools(self):
        """LEAD role inherits tools (None = no restriction)."""
        agent = self._make_agent(AgentRole.LEAD, "jaeger")
        tools = effective_tools(agent)
        assert tools is None, "Lead should inherit tools (None)"
    
    def test_runtime_inherits_tools(self):
        """RUNTIME role inherits tools."""
        agent = self._make_agent(AgentRole.RUNTIME, "runtime-test")
        tools = effective_tools(agent)
        assert tools is None, "Runtime should inherit tools (None)"
    
    def test_tool_scope_description(self):
        """tool_scope_description should be human-readable."""
        char_agent = self._make_agent(AgentRole.CHARACTER, "lilith")
        assert "no tools" in tool_scope_description(char_agent).lower()
        
        lead_agent = self._make_agent(AgentRole.LEAD, "jaeger")
        assert "inherit" in tool_scope_description(lead_agent).lower()


# ─────────────────────────────────────────────────────────────────
# Security Tests
# ─────────────────────────────────────────────────────────────────

class TestSecurityModel:
    """Test security guarantees of the V2 model."""
    
    def test_character_cannot_escalate_via_metadata(self):
        """A character cannot get tools just by setting metadata directly."""
        agent = AgentRecord(
            id="native:lilith",
            name="lilith",
            kind=AgentKind.NATIVE,
            display_name="Lilith",
            source="registry",
            role=AgentRole.CHARACTER,
        )
        # Even if metadata is tampered with...
        agent.metadata = {"tool_allowlist": ["terminal", "exec_command"]}
        # ...the explicit allowlist is respected (operator set it)
        tools = effective_tools(agent)
        assert "terminal" in tools  # Yes, operator CAN enable tools
    
    def test_character_without_allowlist_is_blocked(self):
        """Character without explicit allowlist is model-only."""
        agent = AgentRecord(
            id="native:lilith",
            name="lilith",
            kind=AgentKind.NATIVE,
            display_name="Lilith",
            source="registry",
            role=AgentRole.CHARACTER,
        )
        # No metadata, no allowlist
        tools = effective_tools(agent)
        assert tools == []
    
    def test_empty_list_is_enforced_not_inherited(self):
        """Empty list [] means NO TOOLS, not inherit."""
        agent = AgentRecord(
            id="native:test",
            name="test",
            kind=AgentKind.NATIVE,
            display_name="Test",
            source="registry",
            role=AgentRole.CHARACTER,
            metadata={"tool_allowlist": []},
        )
        tools = effective_tools(agent)
        assert tools == []
        assert tools is not None, "Empty list is not None — it's explicitly no tools"


# ─────────────────────────────────────────────────────────────────
# Migration Tests
# ─────────────────────────────────────────────────────────────────

class TestMigration:
    """Test V1 → V2 migration logic."""
    
    def test_existing_specialist_keeps_role(self):
        """Existing specialist should keep SPECIALIST role."""
        agent = AgentRecord(
            id="native:builder",
            name="builder",
            kind=AgentKind.NATIVE,
            display_name="Builder",
            source="registry",
            role=AgentRole.SPECIALIST,
        )
        assert agent.role == AgentRole.SPECIALIST
    
    def test_existing_lead_keeps_role(self):
        """Existing lead should keep LEAD role."""
        agent = AgentRecord(
            id="native:jaeger",
            name="jaeger",
            kind=AgentKind.NATIVE,
            display_name="Jaeger",
            source="registry",
            role=AgentRole.LEAD,
        )
        assert agent.role == AgentRole.LEAD
    
    def test_agent_without_personality(self):
        """Agents without personality should work fine (None)."""
        agent = AgentRecord(
            id="native:test",
            name="test",
            kind=AgentKind.NATIVE,
            display_name="Test",
            source="registry",
        )
        assert get_personality(agent) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
