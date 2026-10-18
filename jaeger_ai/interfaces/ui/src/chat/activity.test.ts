import { describe, expect, it } from "vitest";
import { activityPhrase, stepsSummary, thinkingPhrase, toolCategory, type ToolPart } from "./activity";

const tool = (toolName: string, state: ToolPart["state"] = "completed", callId = toolName): ToolPart =>
  ({ kind: "toolInvocation", callId, toolName, input: {}, state });

describe("activity", () => {
  it("classifies Jaeger's tool names", () => {
    expect(toolCategory("web_search")).toBe("search");
    expect(toolCategory("browser")).toBe("web");
    expect(toolCategory("shell")).toBe("shell");
    expect(toolCategory("terminal")).toBe("shell");
    expect(toolCategory("execute_code")).toBe("shell");
    expect(toolCategory("npm run build")).toBe("shell");
    expect(toolCategory("read_file")).toBe("read");
    expect(toolCategory("search_files")).toBe("read");
    expect(toolCategory("write_file")).toBe("edit");
    expect(toolCategory("edit_file")).toBe("edit");
    expect(toolCategory("call_agent")).toBe("agent");
    expect(toolCategory("weather")).toBe("other");
  });

  it("names the live activity", () => {
    expect(activityPhrase({ turnId: "t", parts: [tool("web_search", "executing")] })).toBe("Searching the web…");
    expect(activityPhrase({ turnId: "t", parts: [tool("read_file"), tool("shell", "executing", "c2")] })).toBe("Running commands…");
    expect(activityPhrase({ turnId: "t", parts: [tool("git commit", "waitingForConfirmation")] })).toBe("Waiting for your OK");
    expect(activityPhrase({ turnId: "t", parts: [{ kind: "progress", message: "Looking at the roster" }] })).toBe("Looking at the roster…");
    const to = { kind: "handoff", handoffId: "h", agentId: "native:research", agentName: "Research", count: 1, direction: "to" } as const;
    expect(activityPhrase({ turnId: "t", parts: [to] })).toBe("Checking with Research…");
    expect(activityPhrase({ turnId: "t", parts: [to, { ...to, direction: "from" }] })).toBe(thinkingPhrase("t"));
  });

  it("thinks with a phrase that is stable per turn", () => {
    expect(thinkingPhrase("abc")).toBe(thinkingPhrase("abc"));
    expect(new Set(["a", "b", "c", "d", "e", "f"].map(thinkingPhrase)).size).toBeGreaterThan(1);
    expect(activityPhrase({ turnId: "abc", parts: [] })).toBe(thinkingPhrase("abc"));
  });

  it("summarises steps in first-seen order", () => {
    expect(stepsSummary([tool("shell"), tool("read_file", "completed", "r1"), tool("bash", "completed", "s2"),
      tool("read_file", "completed", "r2"), tool("terminal", "completed", "s3")])).toBe("Ran 3 commands · Read 2 files");
    expect(stepsSummary([tool("web_search")])).toBe("Searched the web");
    expect(stepsSummary([tool("write_file"), tool("shell", "executing", "s")])).toBe("Edited 1 file · Ran 1 command · 1 running");
  });
});
