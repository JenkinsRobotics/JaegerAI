import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, expect, it, vi } from "vitest";
import type { JaegerSource } from "../api/source";
import type { GatewayEvent } from "../api/types";
import { MinimalChat } from "./MinimalChat";
import { WebHost } from "./webHost";

vi.mock("./reveal", () => ({ useRevealedText: (text: string) => text }));
beforeEach(() => localStorage.clear());

it("clears the recovery check once observing saved work, streams into one bubble, and leaves the composer separate", async () => {
  let emit!: (event: GatewayEvent) => void;
  const send = vi.fn();
  const source = {
    kind: "live", send,
    agents: async () => [],
    session: async () => ({ session_id: "s", messages: [{ role: "user", request_id: "r", content: "saved request", timestamp: 1793470740 }] }),
    sessionControl: async () => ({ latest_request: { request_id: "r", status: "running" } }),
    requestStatus: async () => ({ session_id: "s", request_id: "r", status: "running", input_text: "saved request" }),
    stream: async (_s: string, _c: number, callback: typeof emit, signal: AbortSignal) => { emit = callback; await new Promise<void>(resolve => signal.addEventListener("abort", () => resolve(), { once: true })); },
  } as unknown as JaegerSource;
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  try {
    await act(async () => root.render(<MinimalChat host={new WebHost(source)} sessionId="s" />));
    await vi.waitFor(() => expect(emit).toBeTypeOf("function"));
    expect(el.textContent).not.toContain("Checking saved work");
    expect(el.textContent).not.toContain("Waiting for progress");
    expect(el.querySelector(".jg-composer .jg-recovery")).toBeNull();
    await act(async () => emit({ event_id: 1, event: "turn.delta", request_id: "r", payload: { delta: "Hel" } }));
    expect(el.querySelector(".jg-bubble--assistant")?.textContent).toBe("Hel");
    expect(el.querySelector(".jg-progress-line")).toBeNull();
    await act(async () => emit({ event_id: 2, event: "turn.delta", request_id: "r", payload: { delta: "lo" } }));
    expect(el.querySelectorAll(".jg-bubble--assistant")).toHaveLength(1);
    expect(el.querySelector(".jg-bubble--assistant")?.textContent).toBe("Hello");
    await act(async () => emit({ event_id: 3, event: "turn.finish", request_id: "r", payload: { output: "Hello" } }));
    expect(el.querySelector('[aria-label^="Stop"]')).toBeNull();
    expect(send).not.toHaveBeenCalled();
  } finally { act(() => root.unmount()); el.remove(); }
});
