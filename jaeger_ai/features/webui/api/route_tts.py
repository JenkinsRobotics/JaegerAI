"""Text-To-Speech (TTS) API route and helper functions.

Decomposed from routes.py for modular WebUI backend architecture.
Supports Edge TTS, ElevenLabs, and OpenAI-compatible engines with SSRF protection,
IP pinning, prosody normalization, and per-client rate limiting.
"""
from __future__ import annotations

import errno
import http.client
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import socket as _socket
import sys
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
    urlopen,
)

from .config import get_config
from .helpers import bad, read_body

logger = logging.getLogger("hermes.webui")






























