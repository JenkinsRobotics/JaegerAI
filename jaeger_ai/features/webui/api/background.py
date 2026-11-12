"""Background and ephemeral task tracking for /background and /btw commands."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()














