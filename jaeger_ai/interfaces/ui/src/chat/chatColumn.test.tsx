import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ChatPart, ChatTurn } from "./host";
import { ProgressLine, StepsFold, segments, showsProgress } from "./MinimalChat";

const tool = (callId: string, toolName: string, state: "completed" | "executing" = "completed"): ChatPart =>
  ({ kind: "toolInvocation", callId, toolName, input: {}, state });
const turn = (parts: ChatPart[], state: ChatTurn["state"] = "pending"): ChatTurn => ({ turnId: "t1", message: "hi", parts, state });

describe("chat column", () => {
  it("folds consecutive tool calls into one steps segment between bubbles", () => {
    const segs = segments([
      { kind: "thinking", text: "plan" }, tool("a", "shell"), tool("b", "read_file"), tool("c", "bash"),
      { kind: "progress", message: "Checking" }, { kind: "markdownContent", text: "done" },
    ]);
    expect(segs.map((s) => Object.keys(s)[0])).toEqual(["bubble", "steps", "bubble"]);
    expect("steps" in segs[1] && segs[1].steps.map((t) => t.callId)).toEqual(["a", "b", "c"]);
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
});
