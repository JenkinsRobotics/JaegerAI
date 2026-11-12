import { describe, expect, it } from "vitest";
import type { GatewayEvent, TraceEnvelope } from "../api/types";
import { columns, foldAll, lamps } from "./model";

let ts = 1000;
const ev = (event: string, t: Partial<TraceEnvelope>): GatewayEvent => ({
  event, payload: {}, trace: { v: 1, run_id: "r", turn_id: "t", parent_span_id: null, name: "", state: null, seq: 0,
    ts: (ts += 1), duration_ms: null, agui: "CUSTOM", kind: "info", span_id: "", ...t } as TraceEnvelope,
});
const turn: GatewayEvent[] = [
  ev("turn.start", { kind: "run", span_id: "run:r", state: "running", name: "turn" }),
  ev("model.started", { kind: "model", span_id: "step:r:1", parent_span_id: "run:r", state: "running", name: "model #1" }),
  ev("turn.delta", { kind: "message", span_id: "step:r:1", parent_span_id: "run:r" }),
  ev("model.finished", { kind: "model", span_id: "step:r:1", parent_span_id: "run:r", state: "succeeded", duration_ms: 900 }),
  ev("tool.started", { kind: "tool", span_id: "tool:c", parent_span_id: "step:r:1", state: "running", name: "list_dir" }),
  ev("approval.request", { kind: "approval", span_id: "approval:a", parent_span_id: "tool:c", state: "waiting", name: "tool" }),
  ev("approval.resolved", { kind: "approval", span_id: "approval:a", parent_span_id: "tool:c", state: "succeeded" }),
  ev("tool.completed", { kind: "tool", span_id: "tool:c", parent_span_id: "step:r:1", state: "succeeded" }),
  ev("turn.finish", { kind: "run", span_id: "run:r", state: "succeeded" }),
];

describe("process model", () => {
  it("builds run > step > tool > approval", () => {
    const s = foldAll(turn);
    const cols = columns(s, "run:r");
    expect(cols.map((c) => c.step.id)).toEqual(["step:r:1"]);
    expect(cols[0].below.map((b) => b.id)).toEqual(["tool:c", "approval:a"]);
    expect(s.spans.get("step:r:1")!.durationMs).toBe(900);
    expect(s.spans.get("tool:c")!.name).toBe("list_dir");
  });
  it("scrubbing replays the state at that moment", () => {
    const waiting = foldAll(turn, 5);
    expect(waiting.spans.get("approval:a")!.state).toBe("waiting");
    expect(lamps(waiting)).toMatchObject({ run: true, tool: true, waiting: true, model: false });
    expect(lamps(foldAll(turn, 1))).toMatchObject({ model: true });
    expect(lamps(foldAll(turn))).toMatchObject({ run: false, waiting: false, fault: false });
  });
  it("ignores events without a trace", () => {
    expect(foldAll([{ event: "backlog.updated" }]).spans.size).toBe(0);
  });
  it("tool progress annotates the open tool without changing its state", () => {
    const tr = (span_id: string, kind: string, state: string | null, parent: string | null = null) =>
      ({ v: 1, run_id: "r", turn_id: "r", span_id, parent_span_id: parent, kind, name: "read_file", state, seq: 0, ts: 1, duration_ms: null, agui: "CUSTOM" });
    const ev = (event: string, trace: unknown, payload: Record<string, unknown> = {}, id = 1) =>
      ({ event_id: id, event, session_id: "s", timestamp: 1, payload, trace } as never);
    const s = foldAll([
      ev("turn.start", tr("run:r", "run", "running"), {}, 1),
      ev("tool.started", tr("tool:a", "tool", "running", "run:r"), {}, 2),
      ev("tool.progress", tr("tool:a", "tool", null, "run:r"), { message: "still running · 10 s", fraction: 0.4 }, 3),
    ], 2);
    const tool = s.spans.get("tool:a")!;
    expect(tool.state).toBe("running");
    expect(tool.detail).toBe("still running · 10 s");
    expect(tool.progress).toBeCloseTo(0.4);
  });
});
