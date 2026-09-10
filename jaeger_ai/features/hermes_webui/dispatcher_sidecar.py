"""Backwards-compatibility shim for Hermes Dispatcher Sidecar.

The sidecar is now unified under `jaeger_ai.features.dispatcher`.
"""
import sys
from jaeger_ai.features.dispatcher import sidecar as _target_mod

for _name, _val in _target_mod.__dict__.items():
    if not _name.startswith("__"):
        globals()[_name] = _val

sys.modules[__name__] = _target_mod

if __name__ == "__main__":
    _target_mod.main()
