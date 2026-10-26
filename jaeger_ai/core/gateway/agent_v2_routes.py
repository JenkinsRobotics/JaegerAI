"""V2 Agent Management Routes — Role, Tools, and Personality management.

These endpoints implement the V2 agent architecture:
- AgentRole.CHARACTER for conversational personas
- Effective tool policy (enforced at runtime)
- Personality overlays from the character library

SECURITY: All modification endpoints are OPERATOR-ONLY.
Agents cannot modify their own role, tools, or personality.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

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

logger = logging.getLogger(__name__)


# Operator-only callers (not agents, not external)
OPERATOR_CALLERS = frozenset({"menubar", "cli", "webui", "ide"})


def _require_operator(request: web.Request) -> web.Response | None:
    """Check that the caller is an operator (not an agent). Returns error response if not."""
    caller = request.get("caller")
    caller_name = getattr(caller, "name", None) if caller else None
    if caller_name not in OPERATOR_CALLERS:
        return web.json_response(
            {"error": "Agent configuration is operator-only"},
            status=403,
        )
    return None


def _get_registry(request: web.Request):
    """Get the agent registry from the app."""
    gateway = request.app.get("jaeger_gateway")
    if gateway and hasattr(gateway, "_registry"):
        return gateway._registry()
    return None


# ─────────────────────────────────────────────────────────────────
# Role Management
# ─────────────────────────────────────────────────────────────────

async def handle_set_agent_role(request: web.Request) -> web.Response:
    """PATCH /v1/agents/{id}/role — Change agent role (operator-only).

    Body: {"role": "lead" | "specialist" | "character" | "runtime",
           "expected_revision": int  (optimistic locking)}
    """
    error = _require_operator(request)
    if error:
        return error
    
    agent_id = request.match_info["id"]
    body = await request.json() if request.can_read_body else {}
    
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be an object"}, status=400)
    
    new_role_str = body.get("role")
    if not new_role_str:
        return web.json_response({"error": "role is required"}, status=400)
    
    try:
        new_role = normalize_agent_role(new_role_str)
    except ValueError:
        return web.json_response(
            {"error": f"Invalid role: {new_role_str}. Must be one of: lead, specialist, character, runtime"},
            status=400,
        )
    
    registry = _get_registry(request)
    if not registry:
        return web.json_response({"error": "Registry not available"}, status=503)
    
    agent = registry.get_agent(agent_id)
    if agent is None:
        return web.json_response({"error": "Agent not found"}, status=404)
    
    # Optimistic locking
    expected_revision = body.get("expected_revision")
    current_revision = agent.metadata.get("revision", 0) if agent.metadata else 0
    if expected_revision is not None and int(expected_revision) != int(current_revision):
        return web.json_response(
            {"error": "Revision conflict. Agent was modified by another client.", 
             "current_revision": current_revision},
            status=409,
        )
    
    old_role = agent.role
    agent.role = new_role
    if agent.metadata is None:
        agent.metadata = {}
    agent.metadata["revision"] = int(current_revision) + 1
    
    # If changing to CHARACTER and no tool policy set, default to no tools
    if new_role == AgentRole.CHARACTER and "tool_allowlist" not in agent.metadata:
        agent.metadata["tool_allowlist"] = []
    
    # Persist
    try:
        registry.save()
    except Exception as e:
        logger.error(f"Failed to save registry after role change: {e}")
        return web.json_response({"error": "Failed to persist change"}, status=500)
    
    logger.info(f"Agent {agent_id} role changed: {old_role.value} → {new_role.value}")
    
    return web.json_response({
        "id": agent.id,
        "role": agent.role.value,
        "previous_role": old_role.value,
        "revision": agent.metadata.get("revision"),
        "effective_tools": effective_tools(agent),
        "tool_scope": tool_scope_description(agent),
    })


# ─────────────────────────────────────────────────────────────────
# Tool Policy Management
# ─────────────────────────────────────────────────────────────────

async def handle_set_agent_tools(request: web.Request) -> web.Response:
    """PATCH /v1/agents/{id}/tools — Set tool allowlist (operator-only).

    Body: {"allowed_tools": [...] | null, "expected_revision": int}
    
    allowed_tools:
        null = inherit from role/context
        []   = no tools (model-only, ENFORCED)
        [...] = specific tools only
    """
    error = _require_operator(request)
    if error:
        return error
    
    agent_id = request.match_info["id"]
    body = await request.json() if request.can_read_body else {}
    
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be an object"}, status=400)
    
    if "allowed_tools" not in body:
        return web.json_response({"error": "allowed_tools is required (use null to inherit)"}, status=400)
    
    allowed_tools = body["allowed_tools"]
    if allowed_tools is not None:
        if not isinstance(allowed_tools, list):
            return web.json_response({"error": "allowed_tools must be a list or null"}, status=400)
        if any(not isinstance(t, str) or not t.strip() for t in allowed_tools):
            return web.json_response({"error": "allowed_tools must contain only non-empty strings"}, status=400)
        allowed_tools = [t.strip() for t in allowed_tools]
    
    registry = _get_registry(request)
    if not registry:
        return web.json_response({"error": "Registry not available"}, status=503)
    
    agent = registry.get_agent(agent_id)
    if agent is None:
        return web.json_response({"error": "Agent not found"}, status=404)
    
    # Optimistic locking
    expected_revision = body.get("expected_revision")
    current_revision = agent.metadata.get("revision", 0) if agent.metadata else 0
    if expected_revision is not None and int(expected_revision) != int(current_revision):
        return web.json_response(
            {"error": "Revision conflict", "current_revision": current_revision},
            status=409,
        )
    
    # Set the tool allowlist
    set_tool_allowlist(agent, allowed_tools)
    if agent.metadata is None:
        agent.metadata = {}
    agent.metadata["revision"] = int(current_revision) + 1
    
    # Persist
    try:
        registry.save()
    except Exception as e:
        logger.error(f"Failed to save registry after tool change: {e}")
        return web.json_response({"error": "Failed to persist change"}, status=500)
    
    effective = effective_tools(agent)
    logger.info(f"Agent {agent_id} tools updated: {tool_scope_description(agent)}")
    
    return web.json_response({
        "id": agent.id,
        "role": agent.role.value,
        "allowed_tools": allowed_tools,
        "effective_tools": effective,
        "tool_scope": tool_scope_description(agent),
        "revision": agent.metadata.get("revision"),
        "enforced": True,  # This is always true — enforcement is at runtime
    })


async def handle_get_agent_tools(request: web.Request) -> web.Response:
    """GET /v1/agents/{id}/tools — Get effective tool list."""
    agent_id = request.match_info["id"]
    
    registry = _get_registry(request)
    if not registry:
        return web.json_response({"error": "Registry not available"}, status=503)
    
    agent = registry.get_agent(agent_id)
    if agent is None:
        return web.json_response({"error": "Agent not found"}, status=404)
    
    effective = effective_tools(agent)
    meta = agent.metadata or {}
    
    return web.json_response({
        "id": agent.id,
        "role": agent.role.value,
        "configured_allowlist": meta.get("tool_allowlist"),
        "effective_tools": effective,
        "tool_scope": tool_scope_description(agent),
        "enforced": True,
        "description": (
            "Tools are enforced at runtime by AllowlistToolExecutor. "
            "The agent cannot call tools outside this list, even via prompt injection."
        ),
    })


# ─────────────────────────────────────────────────────────────────
# Personality Management
# ─────────────────────────────────────────────────────────────────

async def handle_set_agent_personality(request: web.Request) -> web.Response:
    """PATCH /v1/agents/{id}/personality — Attach/detach personality (operator-only).

    Body: {"template_id": "jarvis" | null, "expected_revision": int}
          OR  {"personality": {...} | null, "expected_revision": int}
    """
    error = _require_operator(request)
    if error:
        return error
    
    agent_id = request.match_info["id"]
    body = await request.json() if request.can_read_body else {}
    
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be an object"}, status=400)
    
    registry = _get_registry(request)
    if not registry:
        return web.json_response({"error": "Registry not available"}, status=503)
    
    agent = registry.get_agent(agent_id)
    if agent is None:
        return web.json_response({"error": "Agent not found"}, status=404)
    
    # Optimistic locking
    expected_revision = body.get("expected_revision")
    current_revision = agent.metadata.get("revision", 0) if agent.metadata else 0
    if expected_revision is not None and int(expected_revision) != int(current_revision):
        return web.json_response(
            {"error": "Revision conflict", "current_revision": current_revision},
            status=409,
        )
    
    # Remove personality
    if body.get("personality") is None and "template_id" not in body:
        set_personality(agent, None)
        if agent.metadata is None:
            agent.metadata = {}
        agent.metadata["revision"] = int(current_revision) + 1
        
        try:
            registry.save()
        except Exception as e:
            return web.json_response({"error": "Failed to persist"}, status=500)
        
        return web.json_response({
            "id": agent.id,
            "personality": None,
            "revision": agent.metadata.get("revision"),
        })
    
    # Set personality from template
    template_id = body.get("template_id")
    if template_id:
        # Load from character library
        try:
            from jaeger_ai.features.personality.character import (
                characters_root,
                load_character,
            )
            char_path = characters_root() / template_id
            if not char_path.exists():
                return web.json_response({"error": f"Character template '{template_id}' not found"}, status=404)
            
            char = load_character(char_path)
            
            # Build personality from character
            personality = CharacterPersonality(
                template_id=template_id,
                name=char.personality.name,
                role_description=char.role,
                voice_tone=char.voice_tone,
                voice_id=char.voice_id,
                backstory=char.backstory,
                soul=char.soul,
                speech_patterns=tuple(char.personality.speech_patterns),
                quotes=tuple(char.quotes),
                hexaco_openness=char.personality.hexaco.openness,
                hexaco_conscientiousness=char.personality.hexaco.conscientiousness,
                hexaco_extraversion=char.personality.hexaco.extraversion,
                hexaco_agreeableness=char.personality.hexaco.agreeableness,
                hexaco_neuroticism=char.personality.hexaco.neuroticism,
                hexaco_honesty_humility=char.personality.hexaco.honesty_humility,
                special_strength=char.personality.special.strength,
                special_perception=char.personality.special.perception,
                special_endurance=char.personality.special.endurance,
                special_charisma=char.personality.special.charisma,
                special_intelligence=char.personality.special.intelligence,
                special_agility=char.personality.special.agility,
                special_luck=char.personality.special.luck,
                expr_sarcasm=char.personality.expression.sarcasm,
                expr_warmth=char.personality.expression.warmth,
                expr_verbosity=char.personality.expression.verbosity,
                expr_formality=char.personality.expression.formality,
                expr_directness=char.personality.expression.directness,
                expr_humor=char.personality.expression.humor,
                expr_empathy=char.personality.expression.empathy,
                expr_aggression=char.personality.expression.aggression,
                card_url=f"/v1/characters/{template_id}/card",
                card_thumbnail_url=f"/v1/characters/{template_id}/card",
                personality_version=1,
            )
            
            set_personality(agent, personality)
            
        except Exception as e:
            logger.error(f"Failed to load character template: {e}")
            return web.json_response({"error": f"Failed to load template: {e}"}, status=500)
    else:
        # Set from raw personality dict
        personality_data = body.get("personality")
        if not isinstance(personality_data, dict):
            return web.json_response({"error": "personality must be an object or template_id required"}, status=400)
        
        personality = CharacterPersonality.from_dict(personality_data)
        set_personality(agent, personality)
    
    if agent.metadata is None:
        agent.metadata = {}
    agent.metadata["revision"] = int(current_revision) + 1
    
    # Persist
    try:
        registry.save()
    except Exception as e:
        return web.json_response({"error": "Failed to persist"}, status=500)
    
    personality = get_personality(agent)
    logger.info(f"Agent {agent_id} personality set: {personality.template_id if personality else 'custom'}")
    
    return web.json_response({
        "id": agent.id,
        "personality": personality.to_dict() if personality else None,
        "revision": agent.metadata.get("revision"),
    })


# ─────────────────────────────────────────────────────────────────
# Agent Creation (V2)
# ─────────────────────────────────────────────────────────────────

async def handle_create_character_agent(request: web.Request) -> web.Response:
    """POST /v1/agents/from-character — Create character agent (operator-only).

    Body: {"template_id": "jarvis", "name": "My Jarvis", "tools": [...] | null}
    
    Creates an agent with:
    - role = CHARACTER
    - personality = from template
    - tools = [] (no tools by default, ENFORCED)
    """
    error = _require_operator(request)
    if error:
        return error
    
    body = await request.json() if request.can_read_body else {}
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be an object"}, status=400)
    
    template_id = body.get("template_id")
    if not template_id:
        return web.json_response({"error": "template_id is required"}, status=400)
    
    # Load character template
    try:
        from jaeger_ai.features.personality.character import (
            characters_root,
            load_character,
        )
        char_path = characters_root() / template_id
        if not char_path.exists():
            return web.json_response({"error": f"Character template '{template_id}' not found"}, status=404)
        
        char = load_character(char_path)
    except Exception as e:
        return web.json_response({"error": f"Failed to load template: {e}"}, status=500)
    
    # Build agent name
    custom_name = body.get("name") or char.personality.name
    agent_name = custom_name.lower().replace(" ", "-").replace("_", "-")
    agent_id = f"native:{agent_name}"
    
    # Build personality
    personality = CharacterPersonality(
        template_id=template_id,
        name=char.personality.name,
        role_description=char.role,
        voice_tone=char.voice_tone,
        voice_id=char.voice_id,
        backstory=char.backstory,
        soul=char.soul,
        speech_patterns=tuple(char.personality.speech_patterns),
        quotes=tuple(char.quotes),
        hexaco_openness=char.personality.hexaco.openness,
        hexaco_conscientiousness=char.personality.hexaco.conscientiousness,
        hexaco_extraversion=char.personality.hexaco.extraversion,
        hexaco_agreeableness=char.personality.hexaco.agreeableness,
        hexaco_neuroticism=char.personality.hexaco.neuroticism,
        hexaco_honesty_humility=char.personality.hexaco.honesty_humility,
        special_strength=char.personality.special.strength,
        special_perception=char.personality.special.perception,
        special_endurance=char.personality.special.endurance,
        special_charisma=char.personality.special.charisma,
        special_intelligence=char.personality.special.intelligence,
        special_agility=char.personality.special.agility,
        special_luck=char.personality.special.luck,
        expr_sarcasm=char.personality.expression.sarcasm,
        expr_warmth=char.personality.expression.warmth,
        expr_verbosity=char.personality.expression.verbosity,
        expr_formality=char.personality.expression.formality,
        expr_directness=char.personality.expression.directness,
        expr_humor=char.personality.expression.humor,
        expr_empathy=char.personality.expression.empathy,
        expr_aggression=char.personality.expression.aggression,
        card_url=f"/v1/characters/{template_id}/card",
        card_thumbnail_url=f"/v1/characters/{template_id}/card",
        personality_version=1,
    )
    
    # Tools: default to [] (no tools) for characters
    tools = body.get("tools")
    if tools is None:
        tools = []  # Characters default to no tools
    elif not isinstance(tools, list):
        return web.json_response({"error": "tools must be a list or null"}, status=400)
    
    # Create agent record
    metadata = personality.to_dict()
    metadata["character_template"] = template_id
    metadata["tool_allowlist"] = tools
    metadata["revision"] = 1
    
    agent = AgentRecord(
        id=agent_id,
        name=agent_name,
        kind=AgentKind.NATIVE,
        display_name=custom_name,
        source="registry",
        role=AgentRole.CHARACTER,
        metadata=metadata,
    )
    
    # Register
    registry = _get_registry(request)
    if not registry:
        return web.json_response({"error": "Registry not available"}, status=503)
    
    try:
        registry.register(agent)
        registry.save()
    except Exception as e:
        logger.error(f"Failed to register character agent: {e}")
        return web.json_response({"error": f"Failed to create agent: {e}"}, status=500)
    
    logger.info(f"Created character agent: {agent_id} (template: {template_id})")
    
    return web.json_response({
        "id": agent.id,
        "name": agent.name,
        "display_name": agent.display_name,
        "role": agent.role.value,
        "kind": agent.kind.value,
        "personality": personality.to_dict(),
        "effective_tools": [],
        "tool_scope": "model-only (no tools)",
        "card_url": f"/v1/characters/{template_id}/card",
        "revision": 1,
    }, status=201)


# ─────────────────────────────────────────────────────────────────
# Route Registration
# ─────────────────────────────────────────────────────────────────

def register_agent_v2_routes(app: web.Application) -> None:
    """Register V2 agent management routes."""
    # Role management
    app.router.add_patch("/v1/agents/{id}/role", handle_set_agent_role)
    
    # Tool policy management
    app.router.add_patch("/v1/agents/{id}/tools", handle_set_agent_tools)
    app.router.add_get("/v1/agents/{id}/tools", handle_get_agent_tools)
    
    # Personality management
    app.router.add_patch("/v1/agents/{id}/personality", handle_set_agent_personality)
    
    # V2 agent creation
    app.router.add_post("/v1/agents/from-character", handle_create_character_agent)
    
    logger.info("V2 agent management routes registered: /v1/agents/{id}/role, /tools, /personality, /from-character")
