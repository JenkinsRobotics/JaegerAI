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

it("clears a failed lookup notice after a successful check without resending work", async () => {
  const send = vi.fn();
  const source = {
    kind: "live", send, agents: async () => [],
    session: async () => ({ session_id: "s", messages: [] }),
    sessionControl: vi.fn().mockRejectedValueOnce(new Error("Gateway timed out")).mockResolvedValue({}),
  } as unknown as JaegerSource;
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  try {
    await act(async () => root.render(<MinimalChat host={new WebHost(source)} sessionId="s" />));
    await vi.waitFor(() => expect(el.textContent).toContain("Request lookup unavailable"));
    await act(async () => [...el.querySelectorAll("button")].find(b => b.textContent === "Check again")!.click());
    await vi.waitFor(() => expect(el.textContent).not.toContain("Request lookup unavailable"));
    expect(el.textContent).not.toContain("Previous request outcome unknown");
    expect(send).not.toHaveBeenCalled();
  } finally { act(() => root.unmount()); el.remove(); }
});

it("reconciles a persisted approval card with its durable resolved decision after reload", async () => {
  const approvalStatus = vi.fn().mockResolvedValue({approval_id:"approval-old",status:"resolved",decision:"once"});
  const source = {
    kind:"live", agents:async()=>[], approvalStatus,
    session:async()=>({session_id:"s",messages:[
      {role:"user",request_id:"r",content:"run the safe tool",timestamp:1793470740},
      {role:"assistant",request_id:"r",content:"",timestamp:1793470741,parts:[
        {type:"tool",call_id:"call-old",tool:"shell.run_shell",input:{command:"echo ok"},state:"completed",output:"ok"},
        {type:"approval",approval_id:"approval-old",tool:"shell.run_shell",target:"echo ok",state:"pending"},
      ]},
    ]}),
    stream:async()=>{}, approve:vi.fn(),
  } as unknown as JaegerSource;
  const el=document.createElement("div");document.body.append(el);const root=createRoot(el);
  try {
    await act(async()=>root.render(<MinimalChat host={new WebHost(source)} sessionId="s"/>));
    await vi.waitFor(()=>expect(el.textContent).toContain("Approved"));
    expect(el.textContent).not.toContain("Allow once");
    expect(approvalStatus).toHaveBeenCalledWith("approval-old");
  } finally { act(()=>root.unmount());el.remove(); }
});
