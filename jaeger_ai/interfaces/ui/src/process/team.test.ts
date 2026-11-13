import { describe, expect, it } from "vitest";
import type { GatewayEvent, TraceEnvelope } from "../api/types";
import { foldAll } from "./model";
import { responsibilities, respOf } from "./responsibilities";
import { agentLabel } from "./ProcessView";
import { initials, seedHue } from "../team/AgentAvatar";

let ts = 1000;
const ev = (event: string, t: Partial<TraceEnvelope>, payload: Record<string, unknown> = {}): GatewayEvent => ({
  event, payload: { request_id: "room_1", ...payload }, trace: { v: 1, run_id: "room_1", turn_id: "t", parent_span_id: null, name: "", state: null, seq: 0,
    ts: (ts += 1), duration_ms: null, agui: "CUSTOM", kind: "info", span_id: "", ...t } as TraceEnvelope,
});
const room: GatewayEvent[] = [
  ev("room.started", { kind: "run", span_id: "run:room_1", state: "running", name: "room" }, { members: ["native:a", "native:b"], text: "review" }),
  ev("room.turn", { kind: "subagent", span_id: "agent:t1", parent_span_id: "run:room_1", state: "running", name: "Engineer" }, { turn_id: "t1", agent_id: "native:a", agent_name: "Engineer", status: "running" }),
  ev("subagent.tool.started", { kind: "tool", span_id: "tool:c1", parent_span_id: "agent:t1", state: "running", name: "read_file" }, { tool: "read_file", subagent_id: "t1" }),
  ev("subagent.tool.finished", { kind: "tool", span_id: "tool:c1", parent_span_id: "agent:t1", state: "succeeded" }, { tool: "read_file", subagent_id: "t1" }),
  ev("agent.message", { kind: "message", span_id: "agent:t1" }, { turn_id: "t1", agent_id: "native:a", agent_name: "Engineer", text: "Looks good.  @Design please review" }),
  ev("room.turn", { kind: "subagent", span_id: "agent:t1", parent_span_id: "run:room_1", state: "succeeded" }, { turn_id: "t1", agent_id: "native:a", agent_name: "Engineer", status: "succeeded" }),
  ev("room.turn", { kind: "subagent", span_id: "agent:t2", parent_span_id: "agent:t1", state: "running", name: "Design" }, { turn_id: "t2", parent_turn_id: "t1", agent_id: "native:b", agent_name: "Design", status: "running" }),
];

describe("team runtime in the Process view", () => {
  it("nests a handed-off agent under the agent that called it, with its tools and reply", () => {
    const s = foldAll(room);
    const a = s.spans.get("agent:t1")!;
    expect(a.agentId).toBe("native:a");
    expect(a.children).toEqual(["tool:c1", "agent:t2"]);
    expect(a.detail).toBe("Looks good. @Design please review");
    expect(s.spans.get("agent:t2")!.parent).toBe("agent:t1");
    expect(s.spans.has("agent.message")).toBe(false);
  });
  it("Orchestration card names the agents involved", () => {
    expect(respOf("room.turn")).toBe("orchestration");
    expect(respOf("agent.message")).toBe("orchestration");
    const by = Object.fromEntries(responsibilities(room, room.length - 1, "run:room_1",
      { link: "live", replayed: 0, reconnects: 0, gaps: 0, expired: 0, lastEventAt: null }).map((r) => [r.id, r]));
    expect(by.orchestration.value).toBe("2 agents · Engineer, Design");
    expect(by.orchestration.tone).toBe("active");
    expect(by.orchestration.detail).toContain("Design is working");
  });
  it("labels and faces are stable", () => {
    expect(agentLabel("native:jaeger-design-style")).toBe("Jaeger Design Style");
    expect(initials("Jaeger Design & Style")).toBe("DS");
    expect(seedHue("x")).toEqual(seedHue("x"));
  });
});
