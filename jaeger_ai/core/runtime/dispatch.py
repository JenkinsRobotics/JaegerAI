"""Backwards-compatibility shim for Runtime Dispatch.

Turn routing and worker delegation are now unified under `jaeger_ai.features.dispatcher`.
"""
import sys
from jaeger_ai.features.dispatcher import router as _target_mod

for _name, _val in _target_mod.__dict__.items():
    if not _name.startswith("__"):
        globals()[_name] = _val

sys.modules[__name__] = _target_mod
