import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { mapEvent } from "./eventMap";
import type { ChatPart } from "./host";
import { needsSeparator, segments, separatorLabel } from "./MinimalChat";
import { MiniMarkdown } from "./miniMarkdown";
import { messagesToTurns } from "./webHost";

describe("history (persisted parts)", () => {
  it("restores thinking, tools and handoff markers, with the turn time", () => {
    const turns = messagesToTurns([
      { role: "user", content: "ask research", timestamp: "1792276531.0" },
      {
        role: "assistant", content: "done", parts: [
          { type: "reasoning", text: "plan", duration_ms: 1200 },
          { type: "handoff", direction: "to", handoff_id: "h1", agent_id: "native:research", agent_name: "Research" },
          { type: "tool", call_id: "c1", tool: "read_file", status: "done" },
          { type: "handoff", direction: "from", handoff_id: "h1", agent_id: "native:research" },
          { type: "text", text: "done" },
        ],
      },
    ], (id) => (id === "native:research" ? "Research" : id));
    expect(turns).toHaveLength(1);
    expect(turns[0].createdAt).toBe(1792276531000);
    expect(turns[0].parts.map((p) => p.kind)).toEqual(["thinking", "handoff", "toolInvocation", "handoff", "markdownContent"]);
    expect(turns[0].parts[3]).toMatchObject({ direction: "from", agentName: "Research" });
    expect(turns[0].parts[2]).toMatchObject({ state: "completed", toolName: "read_file" });
  });

  it("keeps an assistant message that has no user turn before it", () => {
    const turns = messagesToTurns([{ role: "assistant", content: "Heads up: the build finished." }]);
    expect(turns).toHaveLength(1);
    expect(turns[0]).toMatchObject({ message: "", parts: [{ kind: "markdownContent", text: "Heads up: the build finished." }] });
  });
});

describe("live tool events", () => {
  it("finishes a tool on the gateway's tool.completed / tool.failed names", () => {
    expect(mapEvent({ event: "tool.completed", payload: { call_id: "c1", tool: "call_agent" } })?.parts[0]).toMatchObject({ state: "completed" });
    expect(mapEvent({ event: "tool.failed", payload: { call_id: "c1", tool: "call_agent", error: "boom" } })?.parts[0]).toMatchObject({ state: "cancelled" });
  });
});

describe("transcript layout", () => {
  const to = (id: string, name: string): ChatPart => ({ kind: "handoff", handoffId: id, agentId: id, agentName: name, count: 1, direction: "to" });

  it("folds back-to-back Messaged markers into one", () => {
    const segs = segments([to("a", "Sweep"), to("b", "Gateway"), { kind: "markdownContent", text: "ok" }]);
    expect(segs).toHaveLength(2);
    expect(segs[0]).toMatchObject({ marker: { agents: [{ id: "a", name: "Sweep" }, { id: "b", name: "Gateway" }] } });
  });

  it("puts a separator on the first turn, a new day, or a 30-minute gap", () => {
    const t = new Date(2026, 9, 17, 15, 0).getTime();
    expect(needsSeparator(undefined, t)).toBe(true);
    expect(needsSeparator(t, t + 10 * 60_000)).toBe(false);
    expect(needsSeparator(t, t + 31 * 60_000)).toBe(true);
    expect(needsSeparator(t, undefined)).toBe(false);
    expect(separatorLabel(t, t)).toMatch(/^Today /);
    expect(separatorLabel(t, t + 86_400_000)).toMatch(/^Yesterday /);
  });
});

describe("markdown", () => {
  it("renders numbered lists, fenced code with Copy, and only http(s) links", () => {
    const html = renderToStaticMarkup(
      <MiniMarkdown onCopy={() => {}} text={"1. one\n2. two\n\n```sh\necho hi\n\nls\n```\n\nSee [docs](https://example.com) or [x](javascript:alert(1))"} />,
    );
    expect(html).toContain("<ol><li>one</li><li>two</li></ol>");
    expect(html).toContain("<pre><code>echo hi\n\nls</code></pre>");
    expect(html).toContain('aria-label="Copy code"');
    expect(html).toContain('href="https://example.com"');
    expect(html).not.toContain('href="javascript:');
  });
});
