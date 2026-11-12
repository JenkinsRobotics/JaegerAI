"""Folder download API route and helper functions.

Decomposed from routes.py for modular WebUI backend architecture.
Streams a zip archive of <session.workspace>/<path> with directory walk size/file limits.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from typing import Any
import urllib.parse as _up
from urllib.parse import parse_qs
import zipfile

from .helpers import bad, j, safe_resolve

logger = logging.getLogger("hermes.webui")


def _content_disposition_value(disposition: str, filename: str) -> str:
    """Build a latin-1-safe Content-Disposition value with RFC 5987 filename*."""
    safe_name = Path(filename).name.replace("\r", "").replace("\n", "")
    ascii_fallback = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in {'"', '\\'} else "_"
        for ch in safe_name
    ).strip(" .")
    if not ascii_fallback:
        suffix = Path(safe_name).suffix
        ascii_suffix = "".join(
            ch if 32 <= ord(ch) < 127 and ch not in {'"', '\\'} else "_"
            for ch in suffix
        )
        ascii_fallback = f"download{ascii_suffix}" if ascii_suffix else "download"
    quoted_name = _up.quote(safe_name, safe="")
    return (
        f'{disposition}; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quoted_name}"
    )









