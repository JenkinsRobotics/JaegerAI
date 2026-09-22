"""Tests for Provider Abstraction & Cognition Profiles (Workstream 14).

Verifies Invariants:
1. 8 Provider States: SUPPORTED, CONFIGURED, CREDENTIALS_AVAILABLE, REACHABLE,
   DISCOVERED, CERTIFIED, AUTHORIZED, ACTIVE.
2. Cognition Profiles tailor context formatting, tool formats, and role certification.
3. Provider swap modifies model routing but strictly preserves Entity Identity (MODEL != AGENT).
4. Missing credentials report provider as unavailable, not as a crash or unhandled failure.
"""
from pathlib import Path
import tempfile
import pytest

from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.models.cognition_profiles import (
    CognitionProfileRegistry,
    ProviderAssessment,
    swap_cognition_provider,
)


def test_provider_assessment_states():
    """Provider assessment correctly distinguishes supported vs credentials available."""
    # Configured with credentials and online
    prov_online = ProviderAssessment(
        provider_id="ollama-cloud",
        display_name="Ollama Cloud",
        supported=True,
        configured=True,
        credentials_available=True,
        reachable=True,
        discovered=True,
        certified=True,
        authorized=True,
        active=True,
    )
    assert prov_online.is_operational is True

    # Supported in code, but no credentials configured (e.g. Anthropic without API key)
    prov_unavail = ProviderAssessment(
        provider_id="anthropic",
        display_name="Anthropic",
        supported=True,
        configured=False,
        credentials_available=False,
        reachable=False,
        error="No credential configured",
    )
    assert prov_unavail.is_operational is False
    assert prov_unavail.supported is True
    assert prov_unavail.credentials_available is False


def test_cognition_profiles_retrieval():
    """Cognition profile contains correct capabilities, tool formatting, and certified roles."""
    reg = CognitionProfileRegistry()

    kimi_profile = reg.get_profile("kimi-k2.7-code:cloud")
    assert kimi_profile.model_id == "kimi-k2.7-code:cloud"
    assert kimi_profile.vision is True
    assert kimi_profile.context_length == 32768
    assert "REACT" in kimi_profile.certified_roles
    assert "VISION" in kimi_profile.certified_roles
    assert kimi_profile.tool_surface_preferences.get("prefer_compact_schema") is True

    claude_profile = reg.get_profile("claude-3-7-sonnet-20250219")
    assert claude_profile.reasoning_behavior == "extended_thinking"
    assert claude_profile.context_length == 200000


def test_provider_swap_preserves_agent_identity():
    """Provider swap changes backend routing while Entity Identity remains 100% immutable."""
    class DummyRuntime:
        def __init__(self):
            self.identity = EntityIdentity(
                entity_id="jaeger-sovereign-42",
                display_name="Jaeger",
                created_at=1700000000.0,
                instance_name="main",
            )
            self.layout = None

    rt = DummyRuntime()
    orig_id = rt.identity.entity_id

    # Swap from ollama to anthropic
    ok, msg = swap_cognition_provider(rt, "anthropic", "claude-3-7-sonnet-20250219")
    assert ok is True
    assert rt.identity.entity_id == orig_id
    assert rt.identity.display_name == "Jaeger"

    # Swap again to openai
    ok2, msg2 = swap_cognition_provider(rt, "openai", "gpt-4o")
    assert ok2 is True
    assert rt.identity.entity_id == orig_id
