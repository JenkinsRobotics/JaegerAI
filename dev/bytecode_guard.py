"""Pytest bootstrap plugin: AGENTS.md §1 bytecode enforcement.

Loaded via ``-p dev.bytecode_guard`` in pyproject addopts. ``-p`` plugins
run during early pytest bootstrap — before conftest.py is imported — which
is the first point where the interpreter's bytecode decision can still be
changed. ``conftest.py``'s own ``sys.dont_write_bytecode`` cannot cover its
own import, which is why bare ``pytest`` runs kept writing
``__pycache__/conftest.pyc`` at the repo root and tripping
``test_repo_root_has_zero_runtime_junk``.
"""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
