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
  CommandPalette,
  ContextXrayBar,
  ScrollFollowMachine,
  StreamingMarkdown,
  StudioTimeline,
  ThinkingDisclosure,
  ToolCallCard,
} from "@jaeger/ui-kit";
import { AvatarStage } from "@jaeger/ui-avatar";
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
    expect(state.messages[0].parts[0].type === "thinking" && state.messages[0].parts[0].streaming).toBe(false);
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

  it("keeps saved turns and gives a new stream its own user and assistant entries", () => {
    const host: BridgeRpcHost = {
      invoke: vi.fn(async () => []) as unknown as BridgeRpcHost["invoke"],
      onEvent: () => () => {},
    };
    const store = new SessionStore("s1", new WkWebViewBridgeTransport(host));
    store.reconcileHistory([{
      id: "asst_r1", session_id: "s1", request_id: "r1",
      role: "assistant", content: "Saved", parts: [{ type: "text", text: "Saved" }], created_at: 1,
    }], 10);
    store.applyEvent({ seq: 11, event: "text.delta", payload: { request_id: "r1", delta: "Duplicate" } }, true);
    store.applyEvent({ seq: 12, event: "run.started", payload: { request_id: "r2", prompt: "Next" } }, true);
    store.applyEvent({ seq: 13, event: "text.delta", payload: { request_id: "r2", delta: "Reply" } }, true);
    store.applyEvent({ seq: 14, event: "run.completed", payload: { request_id: "r2", content: "Reply" } }, true);
    expect(store.getSnapshot().messages.map((message) => [message.role, message.content])).toEqual([
      ["assistant", "Saved"], ["user", "Next"], ["assistant", "Reply"],
    ]);
    store.dispose();
  });

  it("opens live disclosures independently and collapses them as activity moves on", () => {
    const cards = (reasoning: boolean, tools: boolean) => (
      <>
        <ThinkingDisclosure autoOpen={reasoning} part={{ type: "thinking", text: "Live reasoning text" }} />
        <ToolCallCard autoOpen={tools} part={{ type: "tool", callId: "live", toolName: "read_file", status: "completed", output: "Live tool output" }} />
      </>
    );
    const view = render(cards(true, false));
    expect(screen.queryByText("Live reasoning text")).not.toBeNull();
    expect(screen.queryByText("Live tool output")).toBeNull();
    view.rerender(cards(false, true));
    expect(screen.queryByText("Live reasoning text")).toBeNull();
    expect(screen.queryByText("Live tool output")).not.toBeNull();
    view.rerender(cards(false, false));
    expect(screen.queryByText("Live tool output")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /read_file/ }));
    expect(screen.queryByText("Live tool output")).not.toBeNull();
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
    expect(screen.getByRole("link", { name: "Chat" })).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it("@jaeger/ui-features: supports all 4 Antigravity sidebar states from the top header bar", async () => {
    window.localStorage.clear();
    window.history.pushState(null, "", "/");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/v1/chat/session")) {
          return { ok: true, json: async () => ({ session: { session_id: "sess-shell" } }) };
        }
        if (url.includes("/messages")) {
          return { ok: true, json: async () => ({ messages: [], has_older: false, after_seq: 0 }) };
        }
        if (url.includes("/v1/chat/topics")) {
          return { ok: true, json: async () => ({ topics: [] }) };
        }
        if (url.includes("/v1/workflows")) {
          return {
            ok: true,
            json: async () => ({
              workflows: [
                { run_id: "wf-1", name: "Nightly Repo Audit", status: "running", total_steps: 3, next_ready: ["scan"] },
              ],
            }),
          };
        }
        return { ok: true, json: async () => ({ sessions: [], tools: [], workflows: [], facts: [], models: [], all_green: true }) };
      }),
    );

    render(<JaegerApp />);
    const shell = screen.getByTestId("jaeger-modular-app");
    const leftToggle = screen.getByRole("button", { name: "Toggle left sidebar" });
    const rightToggle = screen.getByRole("button", { name: "Toggle right sidebar" });

    // Both sidebar toggles live in the top header bar, never trapped inside the checkpoint rail
    const header = screen.getByRole("banner", { name: "Jaeger toolbar" });
    expect(header.contains(leftToggle)).toBe(true);
    expect(header.contains(rightToggle)).toBe(true);
    expect(screen.queryByRole("button", { name: "Conversation tracker" })).toBeNull();

    // State 1 (initial): Left open, Right closed
    expect(shell.getAttribute("data-left-open")).toBe("true");
    expect(shell.getAttribute("data-right-open")).toBe("false");
    expect(screen.getByRole("link", { name: "Settings" })).toBeVisible();

    // Switch Left Sidebar to Checkpoints tab -> Conversation tracker renders inside left sidebar
    fireEvent.click(screen.getByRole("tab", { name: "Checkpoints" }));
    expect(screen.getByRole("heading", { name: "Conversation tracker" })).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Workspace" }));
    expect(screen.getByRole("link", { name: "Chat" })).toBeVisible();

    // State 2: Both sidebars open (Left + Right simultaneously)
    fireEvent.click(rightToggle);
    expect(shell.getAttribute("data-left-open")).toBe("true");
    expect(shell.getAttribute("data-right-open")).toBe("true");
    expect(screen.getByRole("complementary", { name: "Workspace inspector" })).toBeVisible();
    expect(await screen.findByText("Nightly Repo Audit")).toBeVisible();

    // Search inside right sidebar filters destinations
    const rightSearch = screen.getByRole("searchbox", { name: "Search tabs, tools, tasks and more" });
    fireEvent.change(rightSearch, { target: { value: "Droid" } });
    expect(screen.getByText("Matching Tabs")).toBeVisible();

    // Right sidebar stays available across non-chat destinations and tabs (Avatar, Mind)
    fireEvent.click(screen.getByRole("tab", { name: "Mind" }));
    expect(screen.getByText("24/7 Cognitive Life Loop")).toBeVisible();

    // State 3: Left closed, Right open
    fireEvent.click(leftToggle);
    expect(shell.getAttribute("data-left-open")).toBe("false");
    expect(shell.getAttribute("data-right-open")).toBe("true");

    // State 4: Both sidebars closed (Zen focus)
    fireEvent.click(rightToggle);
    expect(shell.getAttribute("data-left-open")).toBe("false");
    expect(shell.getAttribute("data-right-open")).toBe("false");

    // Keyboard shortcuts Cmd+B and Cmd+. toggle left and right sidebars
    fireEvent.keyDown(window, { key: "b", metaKey: true });
    expect(shell.getAttribute("data-left-open")).toBe("true");
    fireEvent.keyDown(window, { key: ".", metaKey: true });
    expect(shell.getAttribute("data-right-open")).toBe("true");

    vi.unstubAllGlobals();
  });

  it("@jaeger/ui-avatar & Studio kit: renders 2D AvatarStage, Patchmark Markdown, ContextXray, Cmd+K & Timeline", () => {
    const onDryRun = vi.fn();
    render(
      <div>
        <AvatarStage name="Jaeger" mode="2d_character" emotion="happy" cognitiveMode="idle_life" />
        <StreamingMarkdown text="**Bold** and `code`" />
        <ContextXrayBar usedTokens={4096} maxTokens={32768} hostTotalGb={32} hostAvailableGb={12.4} activeModel="gemma4:12b" />
        <CommandPalette open={true} onClose={() => {}} items={[{ id: "1", label: "Open Studio", group: "Nav", onSelect: () => {} }]} />
        <StudioTimeline
          projectTitle="Episode 1"
          clips={[{ id: "c1", track: "video", label: "Intro", startSec: 0, durationSec: 30, status: "ready" }]}
          onDryRun={onDryRun}
        />
      </div>,
    );
    expect(screen.getByText("Playing Minecraft")).toBeTruthy();
    expect(screen.getByText("12.4/32 GB free")).toBeTruthy();
    expect(screen.getByText("Open Studio")).toBeTruthy();
    fireEvent.click(screen.getByText("Safe Dry-Run"));
    expect(onDryRun).toHaveBeenCalled();
  });
});
