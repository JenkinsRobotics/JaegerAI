"""Character Library API routes for Jaeger Gateway.

Exposes the character/personality library to the frontend:
- GET /v1/characters — list all character templates
- GET /v1/characters/{id} — get a specific character
- GET /v1/characters/{id}/card — get character card image (PNG)
- POST /v1/agents/from-template — create an agent from a character template
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from jaeger_ai.features.personality.character import (
    Character,
    characters_root,
    list_characters,
    load_character,
)

logger = logging.getLogger(__name__)


async def handle_character_scene(request: web.Request) -> web.StreamResponse:
    """Read a validated presentation or one declared pack asset."""
    from jaeger_ai.features.personality.scene import MEDIA, scene_asset, scene_presentation
    root = characters_root().resolve()
    folder = (root / request.match_info["id"]).resolve()
    if not folder.is_relative_to(root) or folder == root or not (folder / "character.yaml").is_file():
        raise web.HTTPNotFound()
    char = load_character(folder)
    key = request.match_info.get("asset")
    if key is None:
        return web.json_response(scene_presentation(char), headers={"Cache-Control": "no-cache"})
    asset = scene_asset(char, key)
    if asset is None:
        raise web.HTTPNotFound()
    return web.FileResponse(asset, headers={"Content-Type": MEDIA[asset.suffix.lower()],
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})


def character_to_dict(char: Character) -> dict[str, Any]:
    """Convert a Character to a JSON-serializable dict for the API."""
    personality = char.personality
    
    # Build card URL
    card_url = None
    if char.card and char.root:
        card_path = char.root / char.card
        if card_path.exists():
            card_url = f"/v1/characters/{char.id}/card"
    
    # Traits as dict
    traits = {
        "hexaco": {
            "openness": round(personality.hexaco.openness, 2),
            "conscientiousness": round(personality.hexaco.conscientiousness, 2),
            "extraversion": round(personality.hexaco.extraversion, 2),
            "agreeableness": round(personality.hexaco.agreeableness, 2),
            "neuroticism": round(personality.hexaco.neuroticism, 2),
            "honesty_humility": round(personality.hexaco.honesty_humility, 2),
        },
        "special": {
            "strength": round(personality.special.strength, 2),
            "perception": round(personality.special.perception, 2),
            "endurance": round(personality.special.endurance, 2),
            "charisma": round(personality.special.charisma, 2),
            "intelligence": round(personality.special.intelligence, 2),
            "agility": round(personality.special.agility, 2),
            "luck": round(personality.special.luck, 2),
        },
        "expression": {
            "sarcasm": round(personality.expression.sarcasm, 2),
            "warmth": round(personality.expression.warmth, 2),
            "verbosity": round(personality.expression.verbosity, 2),
            "formality": round(personality.expression.formality, 2),
            "directness": round(personality.expression.directness, 2),
            "humor": round(personality.expression.humor, 2),
            "empathy": round(personality.expression.empathy, 2),
            "aggression": round(personality.expression.aggression, 2),
        },
        "domains": {
            "science": round(personality.domains.science, 2),
            "philosophy": round(personality.domains.philosophy, 2),
            "combat": round(personality.domains.combat, 2),
            "art": round(personality.domains.art, 2),
            "politics": round(personality.domains.politics, 2),
            "technology": round(personality.domains.technology, 2),
            "nature": round(personality.domains.nature, 2),
            "psychology": round(personality.domains.psychology, 2),
        },
    }
    
    # Suggested role based on character type
    suggested_role = "specialist"
    if char.neutral or char.id == "assistant":
        suggested_role = "lead"
    elif any(word in (char.role or "").lower() for word in ["architect", "auditor", "strategist", "principal"]):
        suggested_role = "specialist"
    
    return {
        "id": char.id,
        "name": personality.name,
        "description": personality.description,
        "role": char.role,
        "voice_tone": char.voice_tone,
        "voice_id": char.voice_id,
        "backstory": char.backstory[:500] if char.backstory else "",
        "soul": char.soul,
        "quotes": list(char.quotes)[:5],
        "mannerisms": list(char.mannerisms)[:5],
        "ideals": list(char.ideals)[:5],
        "behaviors": list(char.behaviors)[:5],
        "traits": traits,
        "custom_instructions": personality.custom_instructions,
        "speech_patterns": list(personality.speech_patterns)[:5],
        "card_url": card_url,
        "has_card_image": card_url is not None,
        "neutral": char.neutral,
        "version": char.version,
        "author": char.author,
        "license": char.license,
        "level": char.level,
        "revision": char.revision,
        "suggested_agent_type": suggested_role,
        # Template info
        "template_id": char.id,
        "template_source": "character_library",
    }


async def handle_list_characters(request: web.Request) -> web.Response:
    """GET /v1/characters — List all character templates."""
    try:
        root = characters_root()
        characters = list_characters(root)
        
        return web.json_response({
            "characters": [character_to_dict(c) for c in characters],
            "total": len(characters),
            "source": "character_library",
        })
    except Exception as e:
        logger.error(f"Failed to list characters: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_get_character(request: web.Request) -> web.Response:
    """GET /v1/characters/{id} — Get a specific character."""
    char_id = request.match_info["id"]
    
    try:
        root = characters_root()
        char_path = root / char_id
        
        if not char_path.exists() or not (char_path / "character.yaml").exists():
            return web.json_response({"error": f"Character '{char_id}' not found"}, status=404)
        
        char = load_character(char_path)
        return web.json_response(character_to_dict(char))
    except Exception as e:
        logger.error(f"Failed to load character {char_id}: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_character_card(request: web.Request) -> web.Response:
    """GET /v1/characters/{id}/card — Serve character card image."""
    char_id = request.match_info["id"]
    
    try:
        root = characters_root()
        char_path = root / char_id
        
        if not char_path.exists():
            return web.json_response({"error": "Character not found"}, status=404)
        
        char = load_character(char_path)
        
        # Try to find card image
        card_path = None
        if char.card:
            candidate = char_path / char.card
            if candidate.exists():
                card_path = candidate
        
        # Fallback: look for card.png directly
        if not card_path:
            candidate = char_path / "card.png"
            if candidate.exists():
                card_path = candidate
        
        # Fallback: look in assets/
        if not card_path:
            assets_dir = char_path / "assets"
            if assets_dir.exists():
                for name in ["card.png", "card-320x420.png", "card-master.png"]:
                    candidate = assets_dir / name
                    if candidate.exists():
                        card_path = candidate
                        break
        
        if not card_path or not card_path.exists():
            return web.json_response({"error": "Card image not found"}, status=404)
        
        # Serve the image
        return web.FileResponse(
            card_path,
            headers={
                "Content-Type": "image/png",
                "Cache-Control": "public, max-age=86400",  # Cache for 1 day
            }
        )
    except Exception as e:
        logger.error(f"Failed to serve card for {char_id}: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_create_agent_from_template(request: web.Request) -> web.Response:
    """POST /v1/agents/from-template — Create an agent from a character template.
    
    Body:
    {
        "template_id": "jarvis",
        "name": "My Jarvis",           // Optional: custom name
        "agent_type": "specialist",     // "lead" or "specialist"
        "role": "custom role",          // Optional: override role
        "description": "custom desc"    // Optional: override description
    }
    """
    try:
        body = await request.json()
        template_id = body.get("template_id")
        
        if not template_id:
            return web.json_response({"error": "template_id is required"}, status=400)
        
        # Load the character template
        root = characters_root()
        char_path = root / template_id
        
        if not char_path.exists() or not (char_path / "character.yaml").exists():
            return web.json_response({"error": f"Template '{template_id}' not found"}, status=404)
        
        char = load_character(char_path)
        
        # Build agent payload
        agent_type = body.get("agent_type", char.suggested_agent_type if hasattr(char, 'suggested_agent_type') else "specialist")
        agent_name = body.get("name") or char.personality.name
        agent_role = body.get("role") or char.role
        agent_description = body.get("description") or char.personality.description
        
        # Build personality/prompt from character
        custom_instructions = char.personality.custom_instructions
        if char.backstory:
            custom_instructions = f"{custom_instructions}\n\nBackstory: {char.backstory}".strip()
        
        # Build speech patterns string
        speech_patterns = "\n".join(f"- {p}" for p in char.personality.speech_patterns)
        
        # Create the agent via the existing agents endpoint logic
        # This returns the created agent
        agent_id = f"template:{template_id}:{agent_name.lower().replace(' ', '-')}"
        
        # TODO: Integrate with actual agent store
        # For now, return the agent definition
        agent_response = {
            "id": agent_id,
            "name": agent_name,
            "display_name": agent_name,
            "role": agent_role,
            "description": agent_description,
            "agent_type": agent_type,
            "kind": "jaeger_native",
            "runner": "native",
            "template_id": template_id,
            "template_source": "character_library",
            "personality": {
                "identity": {
                    "role": char.role,
                    "voice_tone": char.voice_tone,
                    "voice_id": char.voice_id,
                },
                "prompt": {
                    "custom_instructions": custom_instructions,
                    "backstory": char.backstory,
                    "speech_patterns": list(char.personality.speech_patterns),
                    "soul": char.soul,
                },
                "traits": character_to_dict(char)["traits"],
            },
            "card_url": f"/v1/characters/{template_id}/card",
            "skills": [],
            "allowed_tools": [],
            "created_at": None,  # Will be set by agent store
            "created_from": "template",
        }
        
        logger.info(f"Created agent from template '{template_id}': {agent_name} ({agent_type})")
        
        return web.json_response(agent_response, status=201)
        
    except Exception as e:
        logger.error(f"Failed to create agent from template: {e}")
        return web.json_response({"error": str(e)}, status=500)


def register_character_routes(app: web.Application) -> None:
    """Register character library routes on the Gateway app."""
    app.router.add_get("/v1/characters", handle_list_characters)
    app.router.add_get("/v1/characters/{id}", handle_get_character)
    app.router.add_get("/v1/characters/{id}/card", handle_character_card)
    app.router.add_get("/v1/characters/{id}/scene", handle_character_scene)
    app.router.add_get("/v1/characters/{id}/scene/assets/{asset}", handle_character_scene)
    app.router.add_post("/v1/agents/from-template", handle_create_agent_from_template)
    
    logger.info("Character library routes registered: /v1/characters, /v1/agents/from-template")
