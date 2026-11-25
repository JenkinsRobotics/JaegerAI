"""Focused test verifying voice service activity tracking refreshes watchdog."""

from __future__ import annotations

import ast
from pathlib import Path


def test_voice_bridges_wire_on_activity_callback():
    """Verify both LocalBridge and GeminiBridge accept on_activity and call _touch()
    on real speech/transcript/client frames so active calls are never killed by the idle watchdog."""
    src = Path("/Users/developer/GitHub/JaegerAI/jaeger_ai/features/voice/realtime/service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    for cls_name in ("LocalBridge", "GeminiBridge"):
        assert cls_name in classes
        methods = {m.name: m for m in classes[cls_name].body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        init_args = [a.arg for a in methods["__init__"].args.args]
        assert "on_activity" in init_args, f"{cls_name}.__init__ must accept on_activity"
        assert "_touch" in methods, f"{cls_name} must define _touch()"
        proc_src = ast.get_source_segment(src, methods["process_frame"]) or ""
        assert proc_src.count("self._touch()") >= 5, f"{cls_name}.process_frame must refresh activity on live frames"
    assert "on_activity=touch_activity" in src
