import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ChatPart, ChatTurn } from "./host";
import { ProgressLine, StepsFold, segments, showsProgress } from "./MinimalChat";

const tool = (callId: string, toolName: string, state: "completed" | "executing" = "completed"): ChatPart =>
  ({ kind: "toolInvocation", callId, toolName, input: {}, state });
const turn = (parts: ChatPart[], state: ChatTurn["state"] = "pending"): ChatTurn => ({ turnId: "t1", message: "hi", parts, state });

describe("chat column", () => {
  it("keeps commentary between chronological reasoning and tool groups", () => {
    const parts: ChatPart[] = [
      { kind: "thinking", text: "plan" }, tool("a", "shell"), { kind: "markdownContent", text: "Looking" }, tool("b", "read_file"), tool("c", "bash"),
      { kind: "progress", message: "Checking" }, { kind: "markdownContent", text: "done" },
    ];
    const segs = segments(parts, "complete");
    expect(segs.map((s) => Object.keys(s)[0])).toEqual(["activity", "activity", "bubble", "activity", "bubble"]);
    expect("activity" in segs[0] && segs[0].activity.every(p=>p.kind==="thinking")).toBe(true);
    expect("activity" in segs[1] && segs[1].activity.filter(p=>p.kind==="toolInvocation").map(t=>t.callId)).toEqual(["a"]);
    expect(segs[2]).toEqual({bubble:[{kind:"markdownContent",text:"Looking"}]});
    expect(segs[4]).toEqual({bubble:[{kind:"markdownContent",text:"done"}]});
    // The same grouping is available while streaming and after completion.
    expect(segments(parts, "pending")).toEqual(segs);
    // A tool left running in an ended turn reads as stopped.
    const stopped = segments([tool("x", "shell", "executing")], "cancelled");
    expect(stopped[0]).toMatchObject({activity:[{state:"cancelled"}]});
  });

  it("lists each step as verb + target, mono for paths and commands", () => {
    const steps = [
      { ...tool("a", "read_file"), input: { path: "src/app.tsx" } },
      { ...tool("b", "web_search"), input: { query: "swift ui shimmer" } },
      tool("c", "npm run build"),
    ] as Extract<ChatPart, { kind: "toolInvocation" }>[];
    const html = renderToStaticMarkup(<StepsFold tools={steps} defaultOpen />);
    expect(html).toContain('<span class="jg-tool__verb">Read</span> <code class="jg-tool__target">src/app.tsx</code>');
    expect(html).toContain('<span class="jg-tool__verb">Searched</span> <span class="jg-tool__target">swift ui shimmer</span>');
    expect(html).toContain('<span class="jg-tool__verb">Ran</span> <code class="jg-tool__target">npm run build</code>');
  });

  it("renders the steps fold collapsed with a summary, expanded on demand", () => {
    const tools = [tool("a", "shell"), tool("b", "read_file"), tool("c", "bash")] as Extract<ChatPart, { kind: "toolInvocation" }>[];
    const closed = renderToStaticMarkup(<StepsFold tools={tools} />);
    expect(closed).toContain("Ran 2 commands · Read 1 file");
    expect(closed).toContain('aria-expanded="false"');
    expect(closed).toContain("Show steps");
    expect(closed).not.toContain("jg-steps__list");
    const open = renderToStaticMarkup(<StepsFold tools={tools} defaultOpen />);
    expect(open).toContain("Hide steps");
    expect(open.match(/<li>/g)).toHaveLength(3);
  });

  it("shows activity before text and during tools, but not a redundant line while text streams", () => {
    expect(showsProgress(turn([]))).toBe(true);
    expect(showsProgress(turn([tool("a", "web_search", "executing")]))).toBe(true);
    expect(showsProgress(turn([{ kind: "markdownContent", text: "Hel" }]))).toBe(false);
    expect(showsProgress(turn([{ kind: "markdownContent", text: "Let me check" }, tool("a", "shell", "executing")]))).toBe(true);
    expect(showsProgress(turn([], "complete"))).toBe(false);
    expect(showsProgress(turn([], "cancelled"))).toBe(false);
    const html = renderToStaticMarkup(<ProgressLine phrase="Searching the web…" />);
    expect(html).toContain('role="status"');
    expect(html).toContain('<span class="jg-progress-text">Searching the web…</span>');
    expect(html).not.toContain("jg-shimmer");
    expect(html).not.toContain("<i>");
    expect(html).not.toContain("jg-progress-dots");
  });

  it("renders only the text in an accessible progress bubble", () => {
    const html = renderToStaticMarkup(<ProgressLine phrase="Working on it" />);
    expect(html).not.toContain("jg-progress-avatar");
    expect(html).toContain('aria-live="polite"');
    expect(html).not.toContain("jg-progress-dots");
  });
});
