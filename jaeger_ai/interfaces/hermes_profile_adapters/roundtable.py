"""Backwards-compatibility shim for Roundtable HTTP adapter.

Roundtable is now unified in `jaeger_ai.features.roundtable`.
"""
import sys
from jaeger_ai.features.roundtable import roundtable as _target_mod

for _name, _val in _target_mod.__dict__.items():
    if not _name.startswith("__"):
        globals()[_name] = _val

sys.modules[__name__] = _target_mod

if __name__ == "__main__":
    _target_mod.run_server()
