"""Self-check for pipeline tracing: record -> trace.jsonl -> baseline,
and the real bus -> recorder -> file delivery path."""

import tempfile
import time
from pathlib import Path

from jaeger_ai.agent import trace
from jaeger_os.transport import topics
from jaeger_os.transport.inproc_bus import InProcBus


def test_record_and_baseline():
    d = Path(tempfile.mkdtemp())
    rec = trace.TraceRecorder(d / "trace.jsonl")
    # A synthetic 2-turn history fed straight through the record path.
    steps = [
        topics.TraceStep(turn_id=1, step_seq=1, kind="input", detail="hi"),
        topics.TraceStep(turn_id=1, step_seq=2, kind="tool",
                         name="web_search", dur_s=0.8),
        topics.TraceStep(turn_id=1, step_seq=3, kind="think", dur_s=1.2),
        topics.TraceStep(turn_id=1, step_seq=4, kind="answer", dur_s=2.5),
        topics.TraceStep(turn_id=2, step_seq=1, kind="input", detail="again"),
        topics.TraceStep(turn_id=2, step_seq=2, kind="tool",
                         name="web_search", dur_s=0.6),
        topics.TraceStep(turn_id=2, step_seq=3, kind="answer", dur_s=1.5),
    ]
    for s in steps:
        rec.on_step(s)

    base = trace.baseline(d / "trace.jsonl")
    assert base["turns"] == 2, base
    assert base["tool_calls"] == 2, base
    assert base["tools"]["web_search"]["calls"] == 2, base
    assert abs(base["total_s"]["avg"] - 2.0) < 1e-6, base       # (2.5+1.5)/2
    assert abs(base["tools"]["web_search"]["avg_s"] - 0.7) < 1e-6, base  # (.8+.6)/2


def test_bus_delivery():
    d = Path(tempfile.mkdtemp())
    bus = InProcBus()
    rec = trace.TraceRecorder(d / "trace.jsonl")
    bus.subscribe(topics.SENSE_TRACE_STEP, rec.on_step)
    bus.publish(topics.TraceStep(turn_id=9, step_seq=1, kind="input", detail="ping"))
    # Delivery runs on the bus thread — wait briefly for the append.
    path = d / "trace.jsonl"
    for _ in range(50):
        if path.exists() and path.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.02)
    bus.close()
    rows = trace.read_steps(path)
    assert rows and rows[0]["turn_id"] == 9 and rows[0]["kind"] == "input", rows


if __name__ == "__main__":
    test_record_and_baseline()
    test_bus_delivery()
    print("trace self-check OK")
