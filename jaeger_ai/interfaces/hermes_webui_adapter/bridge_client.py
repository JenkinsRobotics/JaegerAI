"""Backwards-compatibility shim for Hermes WebUI adapter bridge client.

Bridge client logic is now unified under `jaeger_ai.features.webui.adapter`.
"""
import sys
from jaeger_ai.features.webui.adapter import bridge_client as _target_mod

for _name, _val in _target_mod.__dict__.items():
    if not _name.startswith("__"):
        globals()[_name] = _val

sys.modules[__name__] = _target_mod
