import { describe, expect, it, vi } from "vitest";
import { GatewayError } from "../api/gateway";
import type { JaegerSource, TurnReceipt } from "../api/source";
import type { GatewayEvent } from "../api/types";
import { followTurn } from "./followTurn";
import type { ChatPart } from "./host";
import { WebHost } from "./webHost";

type Stream = JaegerSource["stream"];
const ev = (event_id: number, event: string, request_id: string, payload: Record<string, unknown> = {}): GatewayEvent => ({ event, event_id, request_id, payload });
const noSleep = async () => {};

/** A stream that ignores the cursor and replays everything, the worst case. */
const replayAll = (events: GatewayEvent[]): Stream => async (_s, _c, onEvent) => { events.forEach(onEvent); };

describe("followTurn (review #3)", () => {
  it("does not settle on a replayed finish event from an earlier turn", async () => {
    const parts: ChatPart[] = [];
    const stream = replayAll([
      ev(3, "turn.delta", "old", { delta: "old text" }),
      ev(5, "turn.finish", "old"),
      ev(10, "turn.start", "new"),
      ev(11, "turn.delta", "new", { delta: "hi" }),
      ev(12, "turn.finish", "new"),
    ]);
    const result = await followTurn({ source: { stream }, sessionId: "s", requestId: "new", cursor: 9, signal: new AbortController().signal, onPart: (p) => parts.push(p), sleep: noSleep });
    expect(result.state).toBe("complete");
    expect(parts).toEqual([{ kind: "markdownContent", text: "hi" }]);
  });

  it("drops frames at or below the cursor even when they carry our request id", async () => {
    const parts: ChatPart[] = [];
    const stream = replayAll([ev(8, "turn.failed", "r1", { error: "stale" }), ev(10, "turn.delta", "r1", { delta: "ok" }), ev(11, "turn.finish", "r1")]);
    const result = await followTurn({ source: { stream }, sessionId: "s", requestId: "r1", cursor: 9, signal: new AbortController().signal, onPart: (p) => parts.push(p), sleep: noSleep });
    expect(result.state).toBe("complete");
    expect(parts).toEqual([{ kind: "markdownContent", text: "ok" }]);
  });

  it("only completes on its own finish event (other request or other turn_id is ignored)", async () => {
    const stream = replayAll([
      ev(10, "turn.finish", "other"),
      { ...ev(11, "turn.finish", "r1"), turn_id: "someone-else" },
      ev(12, "turn.delta", "r1", { delta: "x" }),
      { ...ev(13, "turn.finish", "r1"), turn_id: "t1" },
    ]);
    const onCursor = vi.fn();
    const parts: ChatPart[] = [];
    const result = await followTurn({ source: { stream }, sessionId: "s", requestId: "r1", turnId: "t1", cursor: 9, signal: new AbortController().signal, onPart: (p) => parts.push(p), onCursor, sleep: noSleep });
    expect(result.state).toBe("complete");
    expect(parts).toHaveLength(1);
    expect(onCursor).toHaveBeenLastCalledWith(13);
  });

  it("reconnects with backoff and resumes from the last seen cursor", async () => {
    const cursors: Array<number | undefined> = [];
    const sleeps: number[] = [];
    let call = 0;
    const stream: Stream = async (_s, cursor, onEvent) => {
      cursors.push(cursor);
      call += 1;
      if (call === 1) { onEvent(ev(10, "turn.start", "r1")); onEvent(ev(11, "turn.delta", "r1", { delta: "a" })); throw new TypeError("network down"); }
      if (call === 2) throw new TypeError("still down");
      onEvent(ev(11, "turn.delta", "r1", { delta: "a" })); // server replays the edge frame: must be dropped
      onEvent(ev(12, "turn.delta", "r1", { delta: "b" }));
      onEvent(ev(13, "turn.finish", "r1"));
    };
    const parts: ChatPart[] = [];
    const result = await followTurn({
      source: { stream }, sessionId: "s", requestId: "r1", cursor: 9, signal: new AbortController().signal,
      onPart: (p) => parts.push(p), backoffMs: [5, 10, 20], sleep: async (ms) => { sleeps.push(ms); },
    });
    expect(result.state).toBe("complete");
    expect(cursors).toEqual([9, 11, 11]);
    expect(sleeps).toEqual([5, 10]);
    expect(parts.map((p) => (p.kind === "markdownContent" ? p.text : p.kind)).join("")).toBe("ab");
  });

  it("reconnects when the stream ends before the terminal event, and gives up after the backoff budget", async () => {
    const stream: Stream = async () => { /* closes immediately */ };
    const parts: ChatPart[] = [];
    const result = await followTurn({ source: { stream }, sessionId: "s", requestId: "r1", cursor: 0, signal: new AbortController().signal, onPart: (p) => parts.push(p), backoffMs: [1, 1], sleep: noSleep });
    expect(result.state).toBe("failed");
    expect(parts.at(-1)).toMatchObject({ kind: "error" });
  });

  it("fails clearly on 410 cursor expired instead of replaying", async () => {
    const stream: Stream = async () => { throw new GatewayError("Resume cursor is no longer retained", 410); };
    const parts: ChatPart[] = [];
    const result = await followTurn({ source: { stream }, sessionId: "s", requestId: "r1", cursor: 4, signal: new AbortController().signal, onPart: (p) => parts.push(p), sleep: noSleep });
    expect(result.state).toBe("failed");
    expect(parts[0]).toMatchObject({ kind: "error" });
  });
});

describe("WebHost.startTurn", () => {
  const source = (receipt: TurnReceipt, events: GatewayEvent[], seen: Array<number | undefined>): JaegerSource => ({
    kind: "live",
    agents: async () => [], agentsSummary: async () => [], sessions: async () => [],
    session: async (id) => ({ session_id: id, last_event_id: 40 }), createSession: async () => ({ session_id: "s" }),
    send: async () => receipt, addAttachment: async () => ({ attachment_id: "att_x" }), cancel: async () => {}, approve: async () => {}, tasks: async () => [], handoffs: async () => [],
    updateSession: async () => {}, createAgent: async (b) => ({ id: b.name, name: b.name }),
    handoffExchange: async (id) => ({ handoff_id: id, to_agent_id: "a", worker_session_id: "w" }),
    stream: async (_s, cursor, onEvent) => { seen.push(cursor); events.forEach(onEvent); },
  });

  it("streams from start_event_id - 1 and keeps the session cursor for the next turn", async () => {
    const seen: Array<number | undefined> = [];
    const host = new WebHost(source({ request_id: "t1", start_event_id: 50 }, [ev(20, "turn.finish", "t0"), ev(50, "turn.start", "t1"), ev(51, "turn.finish", "t1")], seen), [1]);
    const done = await host.startTurn({ sessionId: "s", turnId: "t1", message: "hi" }, () => {}).done;
    expect(done.state).toBe("complete");
    expect(seen).toEqual([49]);
    expect(host.cursorFor("s")).toBe(51);
  });

  it("seeds the cursor from the loaded session's last_event_id", async () => {
    const seen: Array<number | undefined> = [];
    const host = new WebHost(source({ request_id: "t2" }, [ev(41, "turn.finish", "t2")], seen), [1]);
    await host.sessions.load("s");
    const done = await host.startTurn({ sessionId: "s", turnId: "t2", message: "hi" }, () => {}).done;
    expect(seen).toEqual([40]);
    expect(done.state).toBe("complete");
  });
});


describe("durable terminal answer", () => {
  it.each(["", "MAC-", "MAC-CONTINUITY-OK"])("shows the receipt answer after streamed prefix %j without duplication", async (prefix) => {
    const parts: ChatPart[] = [];
    const events = [ev(10, "turn.delta", "r", { delta: prefix }), ev(11, "turn.finish", "r", { output: "MAC-CONTINUITY-OK", status: "completed" })];
    const result = await followTurn({ source: { stream: replayAll(events) }, sessionId: "fixture", requestId: "r", cursor: 9,
      signal: new AbortController().signal, onPart: (p) => parts.push(p), sleep: noSleep });
    expect(result.state).toBe("complete");
    expect(parts.filter((p) => p.kind === "markdownContent").map((p) => p.text).join("")).toBe("MAC-CONTINUITY-OK");
  });
});


describe("WebHost Stop confirmation", () => {
  it("keeps the turn pending until the Gateway confirms cancellation", async () => {
    let finish!: (event: GatewayEvent) => void;
    const cancel = vi.fn(async () => {});
    const stream: Stream = async (_s, _c, onEvent, signal) => {
      finish = onEvent;
      await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
    };
    const host = new WebHost({ send: async () => ({ request_id: "stop-r", start_event_id: 1 }), cancel, stream } as unknown as JaegerSource);
    const parts: ChatPart[] = [];
    const handle = host.startTurn({ sessionId: "fixture", turnId: "stop-r", message: "owned check" }, (p) => parts.push(p));
    await new Promise((r) => setTimeout(r, 0));
    let settled = false;
    void handle.done.then(() => { settled = true; });
    handle.cancel(); handle.cancel();
    await new Promise((r) => setTimeout(r, 0));
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(settled).toBe(false);
    expect(parts).toContainEqual({ kind: "progress", message: "Stopping… Waiting for Gateway confirmation." });
    finish(ev(2, "turn.cancelled", "stop-r"));
    expect((await handle.done).state).toBe("cancelled");
  });
  it("handles Stop before admission without aborting observation or submitting again", async () => {
    let admit!: (r: TurnReceipt) => void;
    const send = vi.fn(() => new Promise<TurnReceipt>((r) => { admit = r; }));
    const cancel = vi.fn(async () => {});
    const host = new WebHost({ send, cancel, stream: replayAll([ev(2, "turn.cancelled", "assigned")]) } as unknown as JaegerSource);
    const handle = host.startTurn({ sessionId: "fixture", turnId: "client-r", message: "owned check" }, () => {});
    handle.cancel();
    await new Promise((r) => setTimeout(r, 0));
    expect(cancel).not.toHaveBeenCalled();
    admit({ request_id: "assigned", start_event_id: 1 });
    expect((await handle.done).state).toBe("cancelled");
    expect(cancel).toHaveBeenCalledWith("fixture", "assigned");
    expect(send).toHaveBeenCalledTimes(1);
  });
});
