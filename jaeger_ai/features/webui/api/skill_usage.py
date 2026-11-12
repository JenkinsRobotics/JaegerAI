# ── Skill usage reader (read-only) ──
# Note: .usage.json is written by hermes-agent (tools/skill_usage.py).
# WebUI only reads to display usage stats in Insights page.

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


