import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ChatPart, ChatTurn } from "./host";
import { ProgressLine, StepsFold, segments, showsProgress } from "./MinimalChat";

const tool = (callId: string, toolName: string, state: "completed" | "executing" = "completed"): ChatPart =>
  ({ kind: "toolInvocation", callId, toolName, input: {}, state });
const turn = (parts: ChatPart[], state: ChatTurn["state"] = "pending"): ChatTurn => ({ turnId: "t1", message: "hi", parts, state });

describe("chat column", () => {
  it("folds every tool call of a finished turn into ONE steps row below the reply", () => {
    const parts: ChatPart[] = [
      { kind: "thinking", text: "plan" }, tool("a", "shell"), { kind: "markdownContent", text: "Looking" }, tool("b", "read_file"), tool("c", "bash"),
      { kind: "progress", message: "Checking" }, { kind: "markdownContent", text: "done" },
    ];
    const segs = segments(parts, "complete");
    expect(segs.map((s) => Object.keys(s)[0])).toEqual(["bubble", "bubble", "steps"]);
    expect("steps" in segs[2] && segs[2].steps.map((t) => t.callId)).toEqual(["a", "b", "c"]);
    // While running: no tool rows at all, the progress line speaks for them.
    expect(segments(parts, "pending").some((s) => "steps" in s)).toBe(false);
    // A tool left running in an ended turn reads as stopped.
    const stopped = segments([tool("x", "shell", "executing")], "cancelled");
    expect("steps" in stopped[0] && stopped[0].steps[0].state).toBe("cancelled");
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

  it("shows the progress line for the whole pending turn, also while text streams", () => {
    expect(showsProgress(turn([]))).toBe(true);
    expect(showsProgress(turn([tool("a", "web_search", "executing")]))).toBe(true);
    expect(showsProgress(turn([{ kind: "markdownContent", text: "Hel" }]))).toBe(true);
    expect(showsProgress(turn([{ kind: "markdownContent", text: "Let me check" }, tool("a", "shell", "executing")]))).toBe(true);
    expect(showsProgress(turn([], "complete"))).toBe(false);
    expect(showsProgress(turn([], "cancelled"))).toBe(false);
    const html = renderToStaticMarkup(<ProgressLine phrase="Searching the web…" />);
    expect(html).toContain('role="status"');
    expect(html).toContain('<span class="jg-shimmer">Searching the web…</span>');
    expect(html.match(/<i><\/i>/g)).toHaveLength(3);
    expect(html).toContain('class="jg-progress-dots" aria-hidden="true"');
  });

  it("shows the agent's avatar instead of the dots when it knows the agent", () => {
    const html = renderToStaticMarkup(<ProgressLine phrase="Working on it" agent={{ id: "native:jaeger", name: "Jaeger" }} />);
    expect(html).toContain("jg-progress-avatar");
    expect(html).toContain('data-shape="squircle"');
    expect(html).not.toContain("jg-progress-dots");
  });
});
