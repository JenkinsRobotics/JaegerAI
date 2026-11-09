/* Chat stream robustness (2026-11-08): SSE framing edge cases, idempotent part merging and a Stop
 * notice that always resolves. Patterns follow VS Code's chat response model (MIT): content merges only
 * into the last markdown part and the terminal response is authoritative. No VS Code code is copied. */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { decodeSSE, parseSSEChunk } from "../api/sse";
import type { JaegerSource } from "../api/source";
import type { GatewayEvent } from "../api/types";
import { mapEvent } from "./eventMap";
import { applyPart, type ChatPart } from "./host";
import { WebHost } from "./webHost";

beforeEach(() => localStorage.clear());

const body = (...chunks: string[]) => new ReadableStream<Uint8Array>({
  start(c) { const e = new TextEncoder(); chunks.forEach(x => c.enqueue(e.encode(x))); c.close(); },
});
const collect = async (stream: ReadableStream<Uint8Array>) => { const out = []; for await (const f of decodeSSE(stream)) out.push(f); return out; };
const ev = (event_id: number, event: string, request_id: string, payload: Record<string, unknown> = {}): GatewayEvent => ({ event, event_id, request_id, payload });

describe("SSE framing", () => {
  it("accepts lone-CR line endings", () => {
    const { frames, rest } = parseSSEChunk('id: 1\revent: turn.delta\rdata: {"a":1}\r\rid: 2');
    expect(frames).toEqual([{ id: "1", event: "turn.delta", data: { a: 1 } }]);
    expect(rest).toBe("id: 2");
  });
  it("does not split a frame when a CRLF is cut between two network chunks", async () => {
    const frames = await collect(body('id: 1\r\ndata: {"a":1}\r', '\n\r\nid: 2\r\ndata: {"b":2}\r\n\r\n'));
    expect(frames).toEqual([{ id: "1", data: { a: 1 } }, { id: "2", data: { b: 2 } }]);
  });
  it("dispatches a last frame that the server closed without a trailing blank line", async () => {
    const frames = await collect(body('id: 7\nevent: turn.finish\ndata: {"done":true}\n\nid: 8\nevent: turn.finish\ndata: {"x":1}\n'));
    expect(frames.map(f => f.id)).toEqual(["7", "8"]);
  });
  it("keeps a multi-byte character split across chunks intact", async () => {
    const bytes = new TextEncoder().encode('data: {"t":"é✓"}\n\n');
    const stream = new ReadableStream<Uint8Array>({ start(c) { c.enqueue(bytes.slice(0, 12)); c.enqueue(bytes.slice(12)); c.close(); } });
    expect((await collect(stream))[0].data).toEqual({ t: "é✓" });
  });
});

describe("part merging", () => {
  const md = (text: string, extra: Partial<Extract<ChatPart, { kind: "markdownContent" }>> = {}): ChatPart => ({ kind: "markdownContent", text, ...extra });
  it("ignores empty text deltas instead of opening an empty answer bubble", () => {
    expect(applyPart([], md(""))).toEqual([]);
    const live = mapEvent(ev(2, "turn.delta", "r", { delta: "" }))!.parts.reduce(applyPart, [] as ChatPart[]);
    expect(live).toEqual([]);
  });
  it("an empty authoritative final never erases streamed text", () => {
    const parts = [md("Hello")].reduce(applyPart, [] as ChatPart[]);
    expect(applyPart(parts, md("", { role: "final", itemId: "final" }))).toEqual([md("Hello")]);
  });
  it("appends deltas in order into one part", () => {
    const parts = ["He", "llo", " world"].map(t => md(t)).reduce(applyPart, [] as ChatPart[]);
    expect(parts).toEqual([md("Hello world")]);
  });
  it("the terminal answer supersedes provisional AND streamed final items (no duplicated answer)", () => {
    const streamed = [md("Draft "), md("ans", { role: "final", itemId: "msg_1" }), md("wer", { role: "final", itemId: "msg_1" })].reduce(applyPart, [] as ChatPart[]);
    expect(streamed).toEqual([md("answer", { role: "final", itemId: "msg_1" })]);
    const settled = applyPart(streamed, md("answer", { role: "final", itemId: "final" }));
    expect(settled).toEqual([md("answer", { role: "final", itemId: "final" })]);
    // provisional text plus a separate streamed final item: the terminal answer still shows once
    const mixed = [md("Draft "), md("x", { role: "final", itemId: "msg_2" })].reduce(applyPart, [] as ChatPart[]).concat(md("tail"));
    expect(applyPart(mixed, md("Draft x tail", { role: "final", itemId: "final" }))).toEqual([md("Draft x tail", { role: "final", itemId: "final" })]);
  });
  it("keeps commentary written before a tool round when the final answer lands", () => {
    const parts = [
      md("Let me check."),
      { kind: "toolInvocation", callId: "c1", toolName: "search", input: null, state: "completed" } as ChatPart,
      md("Found it", { role: "final", itemId: "msg_9" }),
    ].reduce(applyPart, [] as ChatPart[]);
    const settled = applyPart(parts, md("Found it.", { role: "final", itemId: "final" }));
    expect(settled.filter(p => p.kind === "markdownContent")).toEqual([md("Let me check.", { role: "commentary" }), md("Found it.", { role: "final", itemId: "final" })]);
  });
  it("re-applying the same terminal answer is idempotent", () => {
    const final = md("Answer", { role: "final", itemId: "final" });
    const once = [md("Ans"), md("wer"), final].reduce(applyPart, [] as ChatPart[]);
    expect(applyPart(once, final)).toEqual(once);
  });
  it("a notice with the same id replaces the earlier one in place", () => {
    const parts = [{ kind: "warning", noticeId: "stop", message: "waiting" } as ChatPart, md("x")].reduce(applyPart, [] as ChatPart[]);
    expect(applyPart(parts, { kind: "warning", noticeId: "stop", message: "Stopped." })).toEqual([{ kind: "warning", noticeId: "stop", message: "Stopped." }, md("x")]);
  });
});

describe("Stop notice", () => {
  it("resolves the 'waiting to confirm' notice once the Gateway confirms, without showing raw request ids", async () => {
    let emit!: (event: GatewayEvent) => void;
    const stream: JaegerSource["stream"] = async (_s, _c, onEvent, signal) => {
      emit = onEvent;
      await new Promise<void>(resolve => signal.addEventListener("abort", () => resolve(), { once: true }));
    };
    const cancel = vi.fn(async () => ({ request_id: "req-123", session_id: "s1", cancel_requested: true, cancellation_confirmed: false }));
    const host = new WebHost({ send: async () => ({ request_id: "req-123", start_event_id: 1 }), cancel, stream } as unknown as JaegerSource);
    let parts: ChatPart[] = [];
    const handle = host.startTurn({ sessionId: "s1", turnId: "req-123", message: "long story" }, p => { parts = applyPart(parts, p); });
    await vi.waitFor(() => expect(emit).toBeTypeOf("function"));
    emit(ev(2, "turn.delta", "req-123", { delta: "Once upon" }));
    handle.cancel();
    await vi.waitFor(() => expect(parts.some(p => p.kind === "warning" && /waiting for the Gateway/.test(p.message))).toBe(true));
    expect(JSON.stringify(parts)).not.toMatch(/req-123/);
    emit(ev(3, "turn.cancelled", "req-123"));
    expect((await handle.done).state).toBe("cancelled");
    const notices = parts.filter(p => p.kind === "warning");
    expect(notices).toEqual([{ kind: "warning", noticeId: "stop", message: "Stopped. The Gateway confirmed this request was cancelled." }]);
    expect(parts).toContainEqual({ kind: "markdownContent", text: "Once upon" });
  });
});
