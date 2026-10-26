"""Skill adapters for importing skills from external marketplaces.

Supports:
- Hermes Agent skills (NousResearch/hermes-agent)
- OpenClaw skills (openclaw/openclaw)
- ClawHub marketplace (clawhub.ai)
- agentskills.io specification
"""

from .base import SkillAdapter, ConversionResult
from .hermes import HermesSkillAdapter
from .openclaw import OpenClawSkillAdapter
from .clawhub import ClawHubAdapter, ClawHubClient
from .agentskills import AgentSkillsAdapter, AgentSkillsClient

__all__ = [
    "SkillAdapter",
    "ConversionResult",
    "HermesSkillAdapter",
    "OpenClawSkillAdapter",
    "ClawHubAdapter",
    "ClawHubClient",
    "AgentSkillsAdapter",
    "AgentSkillsClient",
]
