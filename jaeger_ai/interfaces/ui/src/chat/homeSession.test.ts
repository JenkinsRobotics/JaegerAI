import { afterEach, describe, expect, it, vi } from "vitest";
import type { JaegerSource } from "../api/source";
import type { SessionRow } from "../api/types";
import { MockSource } from "../api/mock";
import { mockHome, mockHomeWire } from "../api/mockHome";
import { contractHome, ENTRY_PREFIX, fallbackHome, fromWirePage, HOME_ROUTES, type WirePage } from "./homeSession";

afterEach(() => localStorage.clear());

describe("fromWirePage (provisional wire → UI page)", () => {
  const page: WirePage = {
    has_more: true, before: "c9", last_event_id: 41,
    messages: [
      { id: "s1", kind: "summary", role: "system", summary: { text: "Planned it.", covers_count: 12, from_ts: 100, to_ts: 200 } },
      { id: "u1", role: "user", content: "hi", timestamp: 300 },
      { id: "a1", role: "assistant", content: "hello", timestamp: 301 },
      { id: "p1", kind: "handoff_result", role: "assistant", sender: { agent_id: "agent:swe" }, handoff_id: "h1", title: "Fix", content: "Done.", links: [{ label: "PR", url: "https://x.invalid" }] },
      { id: "a2", role: "assistant", content: "Noted." },
    ],
  };
  it("keeps order, turns summaries and posts into entries, and names turns after message ids", () => {
    const ui = fromWirePage("s", page, (id) => (id === "agent:swe" ? "SWE" : id));
    expect(ui.turns.map((t) => t.turnId)).toEqual([`${ENTRY_PREFIX}s1`, "u1", `${ENTRY_PREFIX}p1`, "reply:a2"]);
    expect(ui.turns[1]).toMatchObject({ message: "hi", parts: [{ kind: "markdownContent", text: "hello" }], createdAt: 300_000 });
    expect(ui.entries[`${ENTRY_PREFIX}s1`]).toEqual({ kind: "summary", id: "s1", text: "Planned it.", count: 12, fromAt: 100_000, toAt: 200_000 });
    expect(ui.entries[`${ENTRY_PREFIX}p1`]).toMatchObject({ kind: "post", post: "handoff", sender: { id: "agent:swe", name: "SWE" }, handoffId: "h1", text: "Done.", links: [{ label: "PR", url: "https://x.invalid" }] });
    expect(ui.before).toBe("c9");
    expect(ui.lastEventId).toBe(41);
  });
  it("has no older cursor at the start of the chat", () => {
    expect(fromWirePage("s", { ...page, has_more: false }, String).before).toBeUndefined();
  });
});

describe("contractHome", () => {
  it("calls exactly the provisional routes and reports the cursor once", async () => {
    const calls: string[] = [];
    const wire = mockHomeWire();
    const onCursor = vi.fn();
    const home = contractHome(async (p) => { calls.push(p); return wire(p); }, { pageSize: 30, onCursor });
    expect(await home.home("native:jaeger")).toBe("s-native:jaeger");
    const newest = await home.page("s-native:jaeger");
    const older = await home.page("s-native:jaeger", newest.before);
    expect(calls).toEqual([HOME_ROUTES.home("native:jaeger"), HOME_ROUTES.page("s-native:jaeger", 30), HOME_ROUTES.page("s-native:jaeger", 30, "p2")]);
    expect(onCursor).toHaveBeenCalledTimes(1);
    expect(older.before).toBeUndefined();
    expect(Object.values(older.entries)[0]).toMatchObject({ kind: "summary", count: 48 });
  });
  it("reads a whole older chat and lists history without the home chat", async () => {
    const home = contractHome(mockHomeWire());
    expect((await home.history("native:jaeger")).map((r) => r.sessionId)).toEqual(["s-old-1", "s-old-2"]);
    const read = await home.read("s-native:jaeger");
    expect(read.before).toBeUndefined();
    expect(read.turns[0].turnId).toBe(`${ENTRY_PREFIX}sum-1`);
  });
});

describe("mockHome", () => {
  it("puts the rich sample transcript after the newest wire page", async () => {
    const page = await mockHome(new MockSource()).page("s-native:jaeger");
    expect(page.turns.slice(0, 2).map((t) => t.turnId)).toEqual([`${ENTRY_PREFIX}post-h7`, `${ENTRY_PREFIX}post-t5`]);
    expect(page.turns.at(-1)?.turnId).toBe("m2");
  });
});

describe("fallbackHome (today's gateway)", () => {
  const row = (id: string, at: number, extra: Partial<SessionRow> = {}): SessionRow => ({ session_id: id, agent_id: "a", last_activity_at: at, message_count: 2, ...extra });
  const source = (rows: SessionRow[], turns = 0) => {
    const created: string[] = [];
    const s = {
      sessions: vi.fn(async () => rows),
      createSession: vi.fn(async () => { created.push("new"); return { session_id: "new" }; }),
      session: vi.fn(async (id: string) => ({ session_id: id, title: "T", agent_id: "a", last_event_id: 7,
        messages: Array.from({ length: turns }, (_, i) => [{ role: "user", content: `q${i}`, request_id: `r${i}` }, { role: "assistant", content: `a${i}` }]).flat() })),
    } as unknown as JaegerSource;
    return { s, created };
  };
  it("picks the most recent chat with messages, skipping archived and empty ones", async () => {
    const { s } = source([row("old", 10), row("arch", 99, { archived: true }), row("empty", 98, { message_count: 0 }), row("recent", 50)]);
    expect(await fallbackHome(s).home("a")).toBe("recent");
  });
  it("prefers the chat this device used last, if it's still open", async () => {
    localStorage.setItem("jaeger.ui.chosen-chat", JSON.stringify({ a: "old" }));
    const { s } = source([row("old", 10), row("recent", 50)]);
    expect(await fallbackHome(s).home("a")).toBe("old");
  });
  it("creates one chat when the agent has none, even when asked twice at once", async () => {
    const { s, created } = source([]);
    const home = fallbackHome(s);
    expect(await Promise.all([home.home("a"), home.home("a")])).toEqual(["new", "new"]);
    expect(created).toEqual(["new"]);
  });
  it("pages turns client-side, oldest page last, and lists the other chats as history", async () => {
    const { s } = source([row("h", 50), row("x", 10)], 5);
    const onCursor = vi.fn();
    const home = fallbackHome(s, { pageSize: 2, onCursor });
    await home.home("a");
    const p1 = await home.page("h");
    expect(p1.turns.map((t) => t.turnId)).toEqual(["r3", "r4"]);
    const p2 = await home.page("h", p1.before);
    expect(p2.turns.map((t) => t.turnId)).toEqual(["r1", "r2"]);
    const p3 = await home.page("h", p2.before);
    expect(p3.turns.map((t) => t.turnId)).toEqual(["r0"]);
    expect(p3.before).toBeUndefined();
    expect(onCursor).toHaveBeenCalledWith("h", 7);
    expect((await home.history("a")).map((r) => r.sessionId)).toEqual(["x"]);
  });
});
