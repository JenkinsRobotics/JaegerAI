"""First-party compatibility shim for hermes_state in JaegerAI.

Transparently forwards all imports to the vendorized hermes_state engine inside jaeger_ai/vendor/hermes_agent.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_VENDOR_DIR = Path(__file__).resolve().parent / "jaeger_ai" / "vendor" / "hermes_agent"
if not _VENDOR_DIR.is_dir():
    _VENDOR_DIR = Path(__file__).resolve().parents[1] / "jaeger_ai" / "vendor" / "hermes_agent"

if str(_VENDOR_DIR) not in sys.path and _VENDOR_DIR.is_dir():
    sys.path.insert(0, str(_VENDOR_DIR))

_target = _VENDOR_DIR / "hermes_state.py"
_spec = importlib.util.spec_from_file_location("hermes_state", _target)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["hermes_state"] = _mod
_spec.loader.exec_module(_mod)

for _name in dir(_mod):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_mod, _name)
