#!/usr/bin/env python3
"""Observability pipeline probe.

Emit a few synthetic turns through the trace bus + recorder, then print
the baseline — proving the trace pipeline (emit → /sense/trace_step →
trace.jsonl → baseline) end to end without needing the agent.

    .venv/bin/python dev/pipelines/tracing.py
"""

import json
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def main() -> int:
    from jaeger_os.agent import trace
    from jaeger_os.core.instance.instance import InstanceLayout

    layout = InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))
    trace.start_trace_recorder(layout)

    turns = [("what's the weather?", "web_search", "Sunny, 68F."),
             ("what time is it?", None, "It's noon."),
             ("thanks", None, "You're welcome.")]
    for i, (q, tool, ans) in enumerate(turns):
        trace.trace_begin("probe", q)
        if tool:
            trace.trace_step("tool", tool, dur_s=0.8, detail="{q} => result")
        trace.trace_step("think", "", dur_s=0.5 + i * 0.2)
        trace.trace_end(ans, 1.5 + i * 0.4)

    time.sleep(0.3)  # let the bus delivery thread flush
    path = layout.logs_dir / "trace.jsonl"
    print(f"wrote {len(path.read_text().splitlines())} steps to {path}\n")
    print(json.dumps(trace.baseline(path), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
