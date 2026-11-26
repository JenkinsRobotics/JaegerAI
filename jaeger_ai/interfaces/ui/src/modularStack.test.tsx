import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  SeqCursor,
  createInitialSessionState,
  parseSSEChunk,
  reduceSessionEvent,
} from "@jaeger/ui-protocol";
import {
  SessionStore,
  StreamingDeltaBatcher,
  WkWebViewBridgeTransport,
  type BridgeRpcHost,
} from "@jaeger/ui-sdk";
import {
  ApprovalCard,
  ScrollFollowMachine,
  ThinkingDisclosure,
  ToolCallCard,
} from "@jaeger/ui-kit";
import { JAEGER_DESTINATIONS, JaegerApp, getDestination } from "@jaeger/ui-features";

describe("100% Modular @jaeger/ui-* Frontend Stack", () => {
  it("@jaeger/ui-protocol: SeqCursor, SSE parser, and versioned session reducer", () => {
    const cursor = new SeqCursor(0);
    expect(cursor.advance(1).accepted).toBe(true);
    expect(cursor.advance(1).accepted).toBe(false);
    expect(cursor.advance(4).gapDetected).toBe(true);
    expect(cursor.lastEventIdHeader).toBe("4");

    const parsed = parseSSEChunk('id: 5\nevent: text.delta\ndata: {"delta":"hello"}\n\n');
    expect(parsed.frames).toEqual([{ id: "5", event: "text.delta", data: { delta: "hello" } }]);

    let state = createInitialSessionState("s1");
    state = reduceSessionEvent(state, { seq: 1, event: "run.started", payload: { request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 2, event: "thinking.delta", payload: { delta: "Plan...", request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 3, event: "tool.started", payload: { call_id: "c1", tool: "read_file", request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 4, event: "tool.completed", payload: { call_id: "c1", tool: "read_file", output: "ok", request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 5, event: "text.delta", payload: { delta: "Done!", request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 6, event: "run.completed", payload: { request_id: "r1" } });

    expect(state.status).toBe("completed");
    expect(state.messages[0].content).toBe("Done!");
    expect(state.messages[0].parts.map((p) => p.type)).toEqual(["thinking", "tool", "text"]);
  });

  it("@jaeger/ui-sdk: write-ahead SessionStore, rollback, and delta batcher", async () => {
    const flushed: string[][] = [];
    const batcher = new StreamingDeltaBatcher<string>((items) => flushed.push(items));
    batcher.push("a");
    batcher.push("b");
    batcher.flushNow();
    expect(flushed).toEqual([["a", "b"]]);
    batcher.dispose();

    const host: BridgeRpcHost = {
      invoke: vi.fn(async (method: string) =>
        method === "runs.submit" ? { request_id: "req-1", status: "queued" } : [],
      ) as unknown as BridgeRpcHost["invoke"],
      onEvent: () => () => {},
    };
    const store = new SessionStore("s-mac", new WkWebViewBridgeTransport(host));
    expect(await store.sendPrompt("Build modular UI", "req-1")).toBe("req-1");
    expect(store.getSnapshot().messages[0].optimistic).toBe(false);
  });

  it("@jaeger/ui-kit: ScrollFollowMachine and pure --jg-* UI primitives", () => {
    const sm = new ScrollFollowMachine();
    sm.transition({ type: "USER_SCROLL_UP" });
    sm.transition({ type: "CONTENT_APPENDED" });
    expect(sm.state).toBe("NEW_CONTENT_BELOW");
    sm.transition({ type: "JUMP_REQUESTED" });
    expect(sm.shouldAutoScroll).toBe(true);
    sm.transition({ type: "REACHED_BOTTOM" });
    expect(sm.state).toBe("FOLLOWING");

    const onDecision = vi.fn();
    render(
      <div>
        <ThinkingDisclosure part={{ type: "thinking", text: "Step 1", durationMs: 1200 }} />
        <ToolCallCard part={{ type: "tool", callId: "t1", toolName: "shell", status: "completed", output: "ok" }} />
        <ApprovalCard
          approval={{ type: "approval", approvalId: "a1", toolName: "shell", prompt: "Allow?", status: "pending" }}
          onDecision={onDecision}
        />
      </div>,
    );
    fireEvent.click(screen.getByText("Approve"));
    expect(onDecision).toHaveBeenCalledWith("a1", "approve");
  });

  it("@jaeger/ui-features: renders JaegerApp with all 5 destinations", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ sessions: [], tools: [], workflows: [], facts: [], models: [], all_green: true }),
      })),
    );
    expect(JAEGER_DESTINATIONS.map((d) => d.id)).toEqual(["chat", "tasks", "tools", "memory", "settings"]);
    expect(getDestination("chat").authoritativeOwner).toBe("gateway");
    render(<JaegerApp />);
    expect(screen.getByTestId("jaeger-modular-app")).toBeTruthy();
    expect(screen.getByText("Jaeger Modular")).toBeTruthy();
    vi.unstubAllGlobals();
  });
});
