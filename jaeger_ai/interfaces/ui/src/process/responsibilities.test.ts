import { describe, expect, it } from "vitest";
import { responsibilities, respOf } from "./responsibilities";

const health = { link: "live" as const, replayed: 12, reconnects: 1, gaps: 0, expired: 0, lastEventAt: null };
let id = 0;
const ev = (event: string, payload: Record<string, unknown>) => ({ event_id: ++id, event, session_id: "s", payload: { request_id: "r1", ...payload } } as never);

describe("eight responsibilities", () => {
  it("are idle until real events arrive (no seeded values)", () => {
    const rows = responsibilities([], -1, "run:r1", health);
    expect(rows.map((r) => r.id)).toEqual(["models", "tools", "loop", "state", "permissions", "orchestration", "reliability", "events"]);
    expect(rows.filter((r) => r.id !== "events").every((r) => r.tone === "idle" && r.value === "—")).toBe(true);
  });

  it("summarise one turn from its events", () => {
    const events = [
      ev("turn.start", {}), ev("route.selected", { model: "grok", reason: "admitted request snapshot", tools: "owner catalog" }),
      ev("model.started", { index: 1, model: "grok", provider: "cli" }),
      ev("model.finished", { index: 1, ok: true, model: "grok", provider: "cli", usage_reported: false, duration_ms: 4200 }),
      ev("loop.iteration", { index: 1, max: 50, decision: "continue", reason: "1 tool call(s) requested" }),
      ev("policy.decision", { tool: "read_file", decision: "allow", policy: "default" }),
      ev("tool.started", { tool: "read_file" }), ev("state.memory", { op: "read", fn: "recall", ok: true, hit: false }),
      ev("tool.completed", { tool: "read_file", elapsed_s: 0.2 }),
      ev("reliability.fallback", { from: "a", to: "b", reason: "RuntimeError" }),
      ev("loop.stop", { reason: "final_answer", ok: true }), ev("state.saved", { what: "session", messages: 2 }),
      ev("model.finished", { index: 9, ok: true, request_id: "other-run" }), // another turn: ignored
    ];
    const by = Object.fromEntries(responsibilities(events, events.length - 1, "run:r1", health).map((r) => [r.id, r]));
    expect(by.models.value).toBe("grok · 4.2 s");
    expect(by.models.detail).toContain("usage not reported");
    expect(by.tools.value).toBe("1 done");
    expect(by.loop.value).toBe("stopped · final_answer");
    expect(by.state.value).toBe("session saved");
    expect(by.permissions.value).toBe("allow · read_file");
    expect(by.orchestration.value).toBe("route · grok");
    expect(by.reliability.tone).toBe("warn");
    expect(by.events.value).toBe("live · 1 reconnect");
    expect(respOf("policy.decision")).toBe("permissions");
  });

  it("attributes a sub-agent's own loop steps to orchestration, not the parent loop", () => {
    const events = [
      ev("loop.iteration", { index: 1, max: 50, decision: "continue", reason: "1 tool call(s) requested" }),
      ev("loop.iteration", { index: 3, max: 24, decision: "answer", reason: "done", subagent_id: "sub_1" }),
      ev("loop.stop", { reason: "final_answer", ok: true, subagent_id: "sub_1" }),
    ];
    const by = Object.fromEntries(responsibilities(events, events.length - 1, "run:r1", health).map((r) => [r.id, r]));
    expect(by.loop.value).toBe("step 1/50 · continue");
    expect(by.orchestration.value).toBe("sub-agent step 3 · answer");
  });
});
