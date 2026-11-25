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
import { JAEGER_DESTINATIONS, getDestination } from "@jaeger/ui-features";

describe("Standalone @jaeger/ui-* modular frontend stack", () => {
  it("@jaeger/ui-protocol: SeqCursor, SSE parser, and versioned session reducer", () => {
    const cursor = new SeqCursor(0);
    expect(cursor.advance(1)).toEqual({
      accepted: true,
      gapDetected: false,
      expectedSeq: 1,
      receivedSeq: 1,
    });
    expect(cursor.advance(1).accepted).toBe(false); // duplicate rejected
    expect(cursor.advance(4).gapDetected).toBe(true); // gap detected
    expect(cursor.lastEventIdHeader).toBe("4");

    const parsed = parseSSEChunk('id: 5\nevent: text.delta\ndata: {"delta":"hello"}\n\n');
    expect(parsed.frames).toHaveLength(1);
    expect(parsed.frames[0]).toEqual({ id: "5", event: "text.delta", data: { delta: "hello" } });

    let state = createInitialSessionState("s1");
    state = reduceSessionEvent(state, { seq: 1, event: "run.started", payload: { request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 2, event: "thinking.delta", payload: { delta: "Plan...", request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 3, event: "tool.started", payload: { call_id: "c1", tool: "read_file", request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 4, event: "tool.completed", payload: { call_id: "c1", tool: "read_file", output: "ok", request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 5, event: "text.delta", payload: { delta: "Done!", request_id: "r1" } });
    state = reduceSessionEvent(state, { seq: 6, event: "run.completed", payload: { request_id: "r1" } });

    expect(state.status).toBe("completed");
    expect(state.messages).toHaveLength(1);
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
      invoke: vi.fn(async (method: string) => {
        if (method === "runs.submit") return { request_id: "req-1", status: "queued" };
        return [];
      }) as unknown as BridgeRpcHost["invoke"],
      onEvent: () => () => {},
    };
    const transport = new WkWebViewBridgeTransport(host);
    const store = new SessionStore("s-mac", transport);
    const rid = await store.sendPrompt("Build modular UI", "req-1");
    expect(rid).toBe("req-1");
    expect(store.getSnapshot().messages).toHaveLength(1);
    expect(store.getSnapshot().messages[0].optimistic).toBe(false);

    // Rollback on transport failure
    const failingHost: BridgeRpcHost = {
      invoke: vi.fn(async () => {
        throw new Error("gateway offline");
      }),
      onEvent: () => () => {},
    };
    const failingStore = new SessionStore("s-fail", new WkWebViewBridgeTransport(failingHost));
    await expect(failingStore.sendPrompt("test")).rejects.toThrow("gateway offline");
    expect(failingStore.getSnapshot().messages).toHaveLength(0);
    expect(failingStore.getSnapshot().status).toBe("failed");
  });

  it("@jaeger/ui-kit: 4-state ScrollFollowMachine and pure --jg-* UI primitives", () => {
    const sm = new ScrollFollowMachine();
    expect(sm.state).toBe("FOLLOWING");
    expect(sm.shouldAutoScroll).toBe(true);
    sm.transition({ type: "USER_SCROLL_UP" });
    expect(sm.state).toBe("USER_PAUSED");
    expect(sm.shouldAutoScroll).toBe(false);
    sm.transition({ type: "CONTENT_APPENDED" });
    expect(sm.state).toBe("NEW_CONTENT_BELOW");
    expect(sm.hasUnreadBelow).toBe(true);
    sm.transition({ type: "JUMP_REQUESTED" });
    expect(sm.state).toBe("JUMPING_TO_BOTTOM");
    expect(sm.shouldAutoScroll).toBe(true);
    sm.transition({ type: "REACHED_BOTTOM" });
    expect(sm.state).toBe("FOLLOWING");

    const onDecision = vi.fn();
    render(
      <div>
        <ThinkingDisclosure part={{ type: "thinking", text: "Step 1", durationMs: 1200 }} />
        <ToolCallCard part={{ type: "tool", callId: "t1", toolName: "shell", status: "completed", output: "ok" }} />
        <ApprovalCard
          approval={{ type: "approval", approvalId: "a1", toolName: "shell", prompt: "Allow deploy?", status: "pending" }}
          onDecision={onDecision}
        />
      </div>,
    );
    expect(screen.getByTestId("thinking-disclosure")).toBeTruthy();
    expect(screen.getByTestId("tool-card-t1")).toBeTruthy();
    fireEvent.click(screen.getByText("Approve"));
    expect(onDecision).toHaveBeenCalledWith("a1", "approve");
  });

  it("@jaeger/ui-features: declares 5 canonical Gateway-owned destinations", () => {
    expect(JAEGER_DESTINATIONS.map((d) => d.id)).toEqual([
      "chat",
      "tasks",
      "tools",
      "memory",
      "settings",
    ]);
    expect(getDestination("chat").authoritativeOwner).toBe("gateway");
  });
});
