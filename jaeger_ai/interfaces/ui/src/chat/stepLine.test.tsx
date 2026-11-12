import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { mapEvent } from "./eventMap";
import { applyPart, type ChatPart } from "./host";
import { ProgressLine, segments, stepLabel } from "./MinimalChat";

const ev = (event: string, payload: Record<string, unknown>) => ({ event_id: 1, event, session_id: "s", timestamp: 1, payload } as never);

describe("live step line", () => {
  it("maps model steps to one step part replaced in place", () => {
    let parts: ChatPart[] = [];
    for (const e of [ev("model.started", { index: 1, model: "grok" }), ev("model.finished", { index: 1, ok: true }),
      ev("model.started", { index: 2, model: "grok" })]) {
      for (const p of mapEvent(e)!.parts) parts = applyPart(parts, p);
    }
    expect(parts).toEqual([{ kind: "step", index: 2, state: "running", model: "grok" }]);
    expect(stepLabel(parts[0] as never)).toBe("Step 2 · grok thinking");
    expect(segments(parts, "pending")).toEqual([]); // never a bubble
  });

  it("links the live line to the Process view for the session", () => {
    render(<ProgressLine phrase="Reading files…" step={{ kind: "step", index: 3, state: "done" }} sessionId="abc" />);
    expect(screen.getByText(/Step 3 · acting/)).toBeTruthy();
    expect(screen.getByText("Watch in Process view").getAttribute("href")).toBe("/work/process?session=abc");
  });
});
