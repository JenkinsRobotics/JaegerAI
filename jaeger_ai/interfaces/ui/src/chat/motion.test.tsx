import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import type { ChatHost } from "./host";
import { MinimalChat } from "./MinimalChat";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("message enter motion", () => {
  it("marks only turns that arrive after the chat loaded as new", async () => {
    const el = document.createElement("div");
    document.body.append(el);
    const root = createRoot(el);
    const host = {
      capabilities: { voice: false }, respondToConfirmation: vi.fn(), copy: vi.fn(), openExternal: vi.fn(),
      startTurn: vi.fn(() => ({ cancel() {}, done: new Promise(() => {}) })),
      sessions: { list: vi.fn(), load: vi.fn(async (id: string) => ({ id, title: "t", turns: [{ turnId: "old", message: "earlier", parts: [], state: "complete" }] })) },
    } as unknown as ChatHost;
    await act(async () => { root.render(<MinimalChat host={host} sessionId="s1" />); });
    const ta = el.querySelector<HTMLTextAreaElement>("textarea")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    await act(async () => { setter.call(ta, "hello"); ta.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => { el.querySelector<HTMLButtonElement>('button[aria-label="Send"]')!.click(); });
    const turns = [...el.querySelectorAll(".jg-turn")];
    expect(turns).toHaveLength(2);
    expect(turns[0].classList.contains("is-new")).toBe(false);
    expect(turns[1].classList.contains("is-new")).toBe(true);
    act(() => root.unmount());
    el.remove();
  });
});
