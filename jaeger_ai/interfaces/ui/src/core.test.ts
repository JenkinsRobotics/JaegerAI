import { describe, expect, it } from "vitest";
import { sidebarRows, visible } from "./agents/agentsLogic";
import { handoffText } from "./agents/HandoffMarker";
import { isUnread } from "./agents/unread";
import { MOCK_AGENTS, MOCK_SUMMARY } from "./api/mock";
import { parseSSEChunk } from "./api/sse";
import { mapEvent } from "./chat/eventMap";
import { applyPart, type ChatPart } from "./chat/host";

describe("sse", () => {
  it("parses frames and keeps the partial tail", () => {
    const { frames, rest } = parseSSEChunk('id: 7\nevent: turn.delta\ndata: {"payload":{"delta":"hi"}}\n\nid: 8\ndata: {"a"');
    expect(frames).toEqual([{ id: "7", event: "turn.delta", data: { payload: { delta: "hi" } } }]);
    expect(rest).toBe('id: 8\ndata: {"a"');
  });
});

describe("eventMap + applyPart", () => {
  it("streams deltas into one markdown part and replaces tool parts by callId", () => {
    let parts: ChatPart[] = [];
    for (const event of [
      { event: "turn.delta", payload: { delta: "Hel" } },
      { event: "turn.delta", payload: { delta: "lo" } },
      { event: "tool.started", payload: { call_id: "c1", tool: "ls" } },
      { event: "tool.done", payload: { call_id: "c1", tool: "ls", output: "ok" } },
    ]) mapEvent(event)?.parts.forEach((p) => { parts = applyPart(parts, p); });
    expect(parts).toHaveLength(2);
    expect(parts[0]).toEqual({ kind: "markdownContent", text: "Hello" });
    expect(parts[1]).toMatchObject({ kind: "toolInvocation", callId: "c1", state: "completed", output: "ok" });
  });
  it("ends turns", () => {
    expect(mapEvent({ event: "turn.finish" })?.state).toBe("complete");
    expect(mapEvent({ event: "turn.failed", payload: { error: "x" } })).toEqual({ parts: [{ kind: "error", message: "x" }], state: "failed" });
  });
});

describe("agents", () => {
  it("hides internal agents, pins the lead, sorts specialists by activity", () => {
    expect(visible(MOCK_AGENTS.find((a) => a.id === "native:gateway")!)).toBe(false);
    const { lead, specialists } = sidebarRows(MOCK_AGENTS, MOCK_SUMMARY);
    expect(lead?.agent.id).toBe("native:jaeger");
    expect(specialists.map((r) => r.agent.id)[0]).toBe("agent:agents-view");
    const times = specialists.map((r) => r.lastActivityAt);
    expect([...times].sort((a, b) => b - a)).toEqual(times);
  });
  it("marker text", () => {
    const base = { kind: "handoff" as const, handoffId: "h", agentId: "a", agentName: "Mac App", count: 1, direction: "to" as const };
    expect(handoffText(base)).toBe("Messaged Mac App");
    expect(handoffText({ ...base, count: 4 })).toBe("4 messages with Mac App");
    expect(handoffText({ ...base, direction: "from" })).toBe("Message from Mac App");
    expect(handoffText({ ...base, agents: [{ id: "a", name: "A" }, { id: "b", name: "B" }] })).toBe("Messaged A and B");
  });
  it("unread uses the local mark, else the server flag", () => {
    expect(isUnread("a", 10, {}, true)).toBe(true);
    expect(isUnread("a", 10, { a: 20 }, true)).toBe(false);
    expect(isUnread("a", 30, { a: 20 }, false)).toBe(true);
  });
});

import { AVATAR_PALETTE, avatarColor } from "./agents/avatarColor";
describe("avatar color", () => {
  it("is deterministic and drawn from Aether tokens", () => {
    expect(avatarColor("agent:mac-app")).toBe(avatarColor("agent:mac-app"));
    expect(AVATAR_PALETTE).toContain(avatarColor("x"));
    expect(avatarColor("x")).toMatch(/^var\(--aether-color-/);
  });
});
