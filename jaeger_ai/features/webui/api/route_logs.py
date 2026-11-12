"""Log inspection and streaming route handlers for WebUI.

Extracted from routes.py to isolate active-profile log tailing logic.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)






