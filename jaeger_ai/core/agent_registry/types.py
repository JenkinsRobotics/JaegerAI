"""Agent identity kinds for the Grok-Bot product shape.

One persistent face (Mac app / WebUI / CLI via gateway) with agents underneath:
Jaeger-native agents created by this framework, plus third-party agents reached
through adapters (Hermes, OpenClaw, Roundtable, …).

Fees/features MUST add capability — never gate fundamentals. The
``fundamentals_gated`` field exists only so callers can assert the invariant;
create/list paths always force it False.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AgentKind(str, Enum):
    """Support model exposed to gateway clients and WebUI."""

    NATIVE = "jaeger_native"
    THIRD_PARTY = "third_party"


class AgentRole(str, Enum):
    """Product role for Grok-shaped lead + specialists + characters chrome.

    Orthogonal to ``AgentKind`` (native vs third-party adapter face).
    
    LEAD: Primary companion, plans and delegates to specialists
    SPECIALIST: Task expert with tool allowlist (Builder, Reviewer, etc.)
    CHARACTER: Conversational persona (Jarvis, Lilith, etc.) — tools off by default
    RUNTIME: Background/runtime agent (hidden from sidebar)
    """

    LEAD = "lead"
    SPECIALIST = "specialist"
    CHARACTER = "character"  # NEW: Conversational persona with personality
    RUNTIME = "runtime"


# Domain labels historically stuffed into metadata.role (surfaces/gateway/everyday).
_SPECIALTY_ALIASES = frozenset({"surfaces", "gateway", "everyday", "specialist"})


def normalize_agent_role(value: object | None, *, default: AgentRole = AgentRole.RUNTIME) -> AgentRole:
    """Coerce role strings; specialty aliases map to ``specialist``."""
    if isinstance(value, AgentRole):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    if raw in _SPECIALTY_ALIASES:
        return AgentRole.SPECIALIST
    try:
        return AgentRole(raw)
    except ValueError:
        return default


def default_role_for(
    *,
    kind: AgentKind | str,
    name: str | None = None,
    agent_id: str | None = None,
    adapter: str | None = None,
) -> AgentRole:
    """Sensible defaults: sticky Assistant is lead; third-party faces are specialists."""
    kind_enum = kind if isinstance(kind, AgentKind) else AgentKind(str(kind))
    needle_name = (name or "").strip().lower()
    needle_id = (agent_id or "").strip().lower()
    if kind_enum is AgentKind.NATIVE:
        if needle_name in {"jaeger", "assistant"} or needle_id in {"native:jaeger", "jaeger"}:
            return AgentRole.LEAD
        if needle_name in _SPECIALTY_ALIASES or needle_id.startswith("native:") and needle_name in {
            "surfaces", "gateway", "everyday",
        }:
            return AgentRole.SPECIALIST
        return AgentRole.RUNTIME
    # Standing third-party adapter faces (Hermes/OpenClaw/Roundtable/…) → specialist.
    _ = adapter  # reserved for future adapter-specific overrides
    return AgentRole.SPECIALIST


# Stable ids for built-in third-party faces (Hermes WebUI profile adapters).
BUILTIN_THIRD_PARTY: tuple[dict[str, Any], ...] = (
    {
        "id": "tp:hermes",
        "name": "hermes",
        "display_name": "Hermes Agent",
        "adapter": "hermes",
        "profile_id": "default",
        "endpoint": None,
        "port": None,
    },
    {
        "id": "tp:openclaw",
        "name": "openclaw",
        "display_name": "OpenClaw",
        "adapter": "openclaw",
        "profile_id": "openclaw",
        "endpoint": "http://127.0.0.1:8644",
        "port": 8644,
    },
    {
        "id": "tp:roundtable",
        "name": "roundtable",
        "display_name": "Roundtable",
        "adapter": "roundtable",
        "profile_id": "roundtable",
        "endpoint": "http://127.0.0.1:8643",
        "port": 8643,
    },
)


@dataclass(slots=True)
class AgentRecord:
    """Serializable agent catalog entry (native or third-party)."""

    id: str
    name: str
    kind: AgentKind
    display_name: str
    source: str  # instance | adapter | registry
    role: AgentRole = AgentRole.RUNTIME
    active: bool = False
    switchable: bool = True
    fundamentals_gated: bool = False
    instance_name: str | None = None
    instance_path: str | None = None
    adapter: str | None = None
    profile_id: str | None = None
    endpoint: str | None = None
    port: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def disabled(self) -> bool:
        """Owner-disabled (``metadata.disabled``): kept in the roster, not routed to."""
        return bool((self.metadata or {}).get("disabled"))

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["kind"] = self.kind.value
        raw["role"] = self.role.value if isinstance(self.role, AgentRole) else str(self.role)
        # Invariant: fundamentals are never fee/feature gated.
        raw["fundamentals_gated"] = False
        raw["switchable"] = True if self.switchable or not self.fundamentals_gated else self.switchable
        raw["switchable"] = True
        raw["fundamentals_gated"] = False
        return raw

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentRecord:
        kind_raw = data.get("kind") or AgentKind.NATIVE.value
        try:
            kind = AgentKind(str(kind_raw))
        except ValueError:
            kind = AgentKind.NATIVE
        meta = dict(data.get("metadata") or {})
        role_hint = data.get("role")
        if role_hint is None:
            if meta.get("specialist") is True or str(meta.get("role") or "") in _SPECIALTY_ALIASES:
                role_hint = AgentRole.SPECIALIST.value
            elif str(meta.get("role") or "") == "lead":
                role_hint = AgentRole.LEAD.value
        role = normalize_agent_role(
            role_hint,
            default=default_role_for(
                kind=kind,
                name=str(data.get("name") or ""),
                agent_id=str(data.get("id") or ""),
                adapter=(str(data["adapter"]) if data.get("adapter") else None),
            ),
        )
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            kind=kind,
            display_name=str(data.get("display_name") or data.get("name") or data["id"]),
            source=str(data.get("source") or "registry"),
            role=role,
            active=bool(data.get("active", False)),
            switchable=True,  # never honor a fee lock from persisted state
            fundamentals_gated=False,
            instance_name=(str(data["instance_name"]) if data.get("instance_name") else None),
            instance_path=(str(data["instance_path"]) if data.get("instance_path") else None),
            adapter=(str(data["adapter"]) if data.get("adapter") else None),
            profile_id=(str(data["profile_id"]) if data.get("profile_id") else None),
            endpoint=(str(data["endpoint"]) if data.get("endpoint") else None),
            port=(int(data["port"]) if data.get("port") is not None else None),
            metadata=dict(data.get("metadata") or {}),
        )


# Explicit type aliases for the support model (documentation + isinstance).
JaegerNativeAgent = AgentRecord
ThirdPartyAgent = AgentRecord


def is_native(record: AgentRecord) -> bool:
    return record.kind is AgentKind.NATIVE


def is_third_party(record: AgentRecord) -> bool:
    return record.kind is AgentKind.THIRD_PARTY


# ─────────────────────────────────────────────────────────────────
# V2: Character Personality System
# ─────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class CharacterPersonality:
    """Personality overlay from the character library.

    Attached to any agent (LEAD, SPECIALIST, or CHARACTER role).
    Provides rich personality traits, voice, and backstory.
    """
    template_id: str | None = None      # "jarvis", "lilith", etc. (None = custom)
    name: str = ""                       # Display name
    role_description: str = ""           # "the operator's AI butler"
    voice_tone: str = ""                 # "crisp, dry, British-butler"
    voice_id: str = "af_heart"           # For TTS
    backstory: str = ""                  # Short version for prompt
    soul: str = ""                       # Core narrative (if exists)
    speech_patterns: tuple[str, ...] = ()
    quotes: tuple[str, ...] = ()
    
    # Trait scores (0.0 - 1.0)
    hexaco_openness: float = 0.5
    hexaco_conscientiousness: float = 0.5
    hexaco_extraversion: float = 0.5
    hexaco_agreeableness: float = 0.5
    hexaco_neuroticism: float = 0.5
    hexaco_honesty_humility: float = 0.5
    special_strength: float = 0.5
    special_perception: float = 0.5
    special_endurance: float = 0.5
    special_charisma: float = 0.5
    special_intelligence: float = 0.5
    special_agility: float = 0.5
    special_luck: float = 0.5
    expr_sarcasm: float = 0.0
    expr_warmth: float = 0.5
    expr_verbosity: float = 0.5
    expr_formality: float = 0.5
    expr_directness: float = 0.5
    expr_humor: float = 0.3
    expr_empathy: float = 0.5
    expr_aggression: float = 0.0
    
    # Rendering
    card_url: str | None = None          # "/v1/characters/jarvis/card"
    card_thumbnail_url: str | None = None
    
    # Version tracking for template updates
    personality_version: int = 1
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage in agent metadata."""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "role_description": self.role_description,
            "voice_tone": self.voice_tone,
            "voice_id": self.voice_id,
            "backstory": self.backstory,
            "soul": self.soul,
            "speech_patterns": list(self.speech_patterns),
            "quotes": list(self.quotes),
            "traits": {
                "hexaco": {
                    "openness": self.hexaco_openness,
                    "conscientiousness": self.hexaco_conscientiousness,
                    "extraversion": self.hexaco_extraversion,
                    "agreeableness": self.hexaco_agreeableness,
                    "neuroticism": self.hexaco_neuroticism,
                    "honesty_humility": self.hexaco_honesty_humility,
                },
                "special": {
                    "strength": self.special_strength,
                    "perception": self.special_perception,
                    "endurance": self.special_endurance,
                    "charisma": self.special_charisma,
                    "intelligence": self.special_intelligence,
                    "agility": self.special_agility,
                    "luck": self.special_luck,
                },
                "expression": {
                    "sarcasm": self.expr_sarcasm,
                    "warmth": self.expr_warmth,
                    "verbosity": self.expr_verbosity,
                    "formality": self.expr_formality,
                    "directness": self.expr_directness,
                    "humor": self.expr_humor,
                    "empathy": self.expr_empathy,
                    "aggression": self.expr_aggression,
                },
            },
            "card_url": self.card_url,
            "card_thumbnail_url": self.card_thumbnail_url,
            "personality_version": self.personality_version,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CharacterPersonality:
        """Deserialize from agent metadata dict."""
        traits = data.get("traits", {})
        hexaco = traits.get("hexaco", {})
        special = traits.get("special", {})
        expr = traits.get("expression", {})
        
        return cls(
            template_id=data.get("template_id"),
            name=data.get("name", ""),
            role_description=data.get("role_description", ""),
            voice_tone=data.get("voice_tone", ""),
            voice_id=data.get("voice_id", "af_heart"),
            backstory=data.get("backstory", ""),
            soul=data.get("soul", ""),
            speech_patterns=tuple(data.get("speech_patterns", [])),
            quotes=tuple(data.get("quotes", [])),
            hexaco_openness=hexaco.get("openness", 0.5),
            hexaco_conscientiousness=hexaco.get("conscientiousness", 0.5),
            hexaco_extraversion=hexaco.get("extraversion", 0.5),
            hexaco_agreeableness=hexaco.get("agreeableness", 0.5),
            hexaco_neuroticism=hexaco.get("neuroticism", 0.5),
            hexaco_honesty_humility=hexaco.get("honesty_humility", 0.5),
            special_strength=special.get("strength", 0.5),
            special_perception=special.get("perception", 0.5),
            special_endurance=special.get("endurance", 0.5),
            special_charisma=special.get("charisma", 0.5),
            special_intelligence=special.get("intelligence", 0.5),
            special_agility=special.get("agility", 0.5),
            special_luck=special.get("luck", 0.5),
            expr_sarcasm=expr.get("sarcasm", 0.0),
            expr_warmth=expr.get("warmth", 0.5),
            expr_verbosity=expr.get("verbosity", 0.5),
            expr_formality=expr.get("formality", 0.5),
            expr_directness=expr.get("directness", 0.5),
            expr_humor=expr.get("humor", 0.3),
            expr_empathy=expr.get("empathy", 0.5),
            expr_aggression=expr.get("aggression", 0.0),
            card_url=data.get("card_url"),
            card_thumbnail_url=data.get("card_thumbnail_url"),
            personality_version=data.get("personality_version", 1),
        )


def get_personality(record: AgentRecord) -> CharacterPersonality | None:
    """Extract personality from agent metadata, or None if not set."""
    meta = record.metadata or {}
    personality_data = meta.get("personality")
    if personality_data and isinstance(personality_data, dict):
        return CharacterPersonality.from_dict(personality_data)
    return None


def set_personality(record: AgentRecord, personality: CharacterPersonality | None) -> None:
    """Set personality on agent metadata."""
    if record.metadata is None:
        record.metadata = {}
    if personality is None:
        record.metadata.pop("personality", None)
        record.metadata.pop("character_template", None)
    else:
        record.metadata["personality"] = personality.to_dict()
        if personality.template_id:
            record.metadata["character_template"] = personality.template_id
