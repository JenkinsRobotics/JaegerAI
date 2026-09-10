"""Backwards-compatibility shim for Roundtable progress.

Roundtable is now unified in `jaeger_ai.features.roundtable`.
"""
import sys
from jaeger_ai.features.roundtable import progress as _target_mod

for _name, _val in _target_mod.__dict__.items():
    if not _name.startswith("__"):
        globals()[_name] = _val

sys.modules[__name__] = _target_mod
