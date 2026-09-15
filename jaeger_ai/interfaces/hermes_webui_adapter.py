"""Backward-compatibility shim for launchd and external callers."""
from jaeger_ai.features.webui.adapter.server import main

if __name__ == "__main__":
    raise SystemExit(main())
