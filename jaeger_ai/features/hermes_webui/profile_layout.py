"""Backwards-compatibility shim for Hermes WebUI profile layout.

WebUI profile layout logic is now unified under `jaeger_ai.features.webui.service`.
"""
import sys
from jaeger_ai.features.webui.service import profile_layout as _target_mod

for _name, _val in _target_mod.__dict__.items():
    if not _name.startswith("__"):
        globals()[_name] = _val

sys.modules[__name__] = _target_mod
