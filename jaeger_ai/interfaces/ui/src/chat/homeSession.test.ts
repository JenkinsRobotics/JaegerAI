import { afterEach, describe, expect, it, vi } from "vitest";
import type { JaegerSource } from "../api/source";
import type { SessionRow } from "../api/types";
import { MockSource } from "../api/mock";
import { MOCK_MESSAGES, mockHome, mockHomeWire, mockPost } from "../api/mockHome";
import { contractHome, ENTRY_PREFIX, fallbackHome, fromWirePage, HOME_ROUTES, toMs, type HomeLiveEvent, type WireMessage, type WirePage } from "./homeSession";

afterEach(() => localStorage.clear());

const W = (m: Partial<WireMessage> & { id: string | number }): WireMessage => ({ session_id: "s", role: "assistant", kind: "message", content: "", created_at: 0, ...m });

describe("fromWirePage (contract wire → UI page)", () => {
  // Newest first, as the route returns it.
  const page: WirePage = {
    next_before: "s1",
    messages: [
      W({ id: "a2", content: "Noted.", created_at: 500 }),
      W({ id: "p1", kind: "handoff_result", sender_agent_id: "agent:swe", content: "Done.", created_at: 400, links: { handoff_id: "h1", child_session_id: "s-swe" } }),
      W({ id: "r1", kind: "handoff_request", sender_agent_id: "native:jaeger", content: "Asked SWE.", created_at: 350, links: { handoff_id: "h1" } }),
      W({ id: "a1", content: "hello", created_at: 301 }),
      W({ id: "u1", role: "user", content: "hi", created_at: 300 }),
      W({ id: "s1", kind: "summary", role: "system", content: "Planned it.", created_at: 200, summary: { covers_from: 100, covers_to: 200, message_count: 12 } }),
    ],
  };
  const names = (id: string) => ({ "agent:swe": "SWE", "native:jaeger": "Jaeger" })[id] ?? id;
  it("orders oldest first, turns summaries and posts into entries, and names turns after message ids", () => {
    const ui = fromWirePage("s", page, names);
    expect(ui.turns.map((t) => t.turnId)).toEqual([`${ENTRY_PREFIX}s1`, "u1", `${ENTRY_PREFIX}r1`, `${ENTRY_PREFIX}p1`, "reply:a2"]);
    expect(ui.turns[1]).toMatchObject({ message: "hi", parts: [{ kind: "markdownContent", text: "hello" }], createdAt: 300_000 });
    expect(ui.entries[`${ENTRY_PREFIX}s1`]).toEqual({ kind: "summary", id: "s1", text: "Planned it.", count: 12, fromAt: 100_000, toAt: 200_000 });
    expect(ui.entries[`${ENTRY_PREFIX}r1`]).toMatchObject({ kind: "post", post: "handoff_request", sender: { id: "native:jaeger", name: "Jaeger" }, handoffId: "h1" });
    expect(ui.entries[`${ENTRY_PREFIX}p1`]).toMatchObject({ kind: "post", post: "handoff", sender: { id: "agent:swe", name: "SWE" }, handoffId: "h1", childSessionId: "s-swe", text: "Done." });
    expect(ui.before).toBe("s1");
  });
  it("has no older cursor when next_before is null; ISO created_at works too", () => {
    const ui = fromWirePage("s", { next_before: null, messages: [W({ id: "u", role: "user", content: "x", created_at: "2026-10-18T18:00:00Z" })] }, String);
    expect(ui.before).toBeUndefined();
    expect(ui.turns[0].createdAt).toBe(Date.parse("2026-10-18T18:00:00Z"));
    expect(toMs("not-a-date")).toBeUndefined();
  });
});

describe("contractHome", () => {
  it("calls exactly the contract routes: home, newest page, older page by message id", async () => {
    const calls: string[] = [];
    const wire = mockHomeWire();
    const home = contractHome(async (p) => { calls.push(p); return wire(p); });
    expect(await home.home("native:jaeger")).toBe("s-native:jaeger");
    const newest = await home.page("s-native:jaeger");
    expect(newest.before).toBe("old-4");
    const older = await home.page("s-native:jaeger", newest.before);
    expect(calls).toEqual([
      "/v1/agents/native%3Ajaeger/home",
      "/v1/sessions/s-native%3Ajaeger/messages?limit=50",
      "/v1/sessions/s-native%3Ajaeger/messages?before=old-4&limit=50",
    ]);
    expect(older.before).toBeUndefined();
    expect(Object.values(older.entries)[0]).toMatchObject({ kind: "summary", count: 48 });
    expect(HOME_ROUTES.page("x", 999)).toBe("/v1/sessions/x/messages?limit=200");
  });
  it("lists older chats from GET /v1/sessions?agent_id= without the home chat, and reads one whole", async () => {
    const calls: string[] = [];
    const wire = mockHomeWire();
    const home = contractHome(async (p) => { calls.push(p); return wire(p); });
    expect((await home.history("native:jaeger")).map((r) => r.sessionId)).toEqual(["s-old-1", "s-old-2"]);
    expect(calls).toContain("/v1/sessions?agent_id=native%3Ajaeger");
    expect(calls.some((c) => c.includes("/history"))).toBe(false);
    const read = await home.read("s-native:jaeger");
    expect(read.before).toBeUndefined();
    expect(read.turns[0].turnId).toBe(`${ENTRY_PREFIX}sum-1`);
  });
  it("delivers message.created posts and session.summarized live from the session stream (mock stream)", async () => {
    const source = new MockSource();
    const onCursor = vi.fn();
    const home = contractHome(mockHomeWire(), { onCursor }, source.stream.bind(source));
    const sid = await home.home("native:jaeger");
    const keep = MOCK_MESSAGES[sid].length;
    const seen: HomeLiveEvent[] = [];
    const controller = new AbortController();
    const running = home.live!(sid, (e) => seen.push(e), controller.signal);
    await new Promise((r) => setTimeout(r, 0));
    expect(onCursor).toHaveBeenCalledWith(sid, 0);
    mockPost((s, e) => source.emit(s, e), W({ id: "live-1", session_id: sid, kind: "task_result", sender_agent_id: "agent:swe", content: "Built.", created_at: 900, links: { task_id: "t9" } }));
    mockPost((s, e) => source.emit(s, e), W({ id: "live-m", session_id: sid, content: "plain" }));
    mockPost((s, e) => source.emit(s, e), W({ id: "live-s", session_id: sid, role: "system", kind: "summary", content: "Sum.", summary: { message_count: 3 } }));
    mockPost((s, e) => source.emit(s, e), W({ id: "other", session_id: "s-elsewhere", kind: "task_result", content: "x" }));
    expect(seen.map((e) => e.type)).toEqual(["entry", "entry", "summarized"]);
    expect(seen[0].type === "entry" && seen[0].page.entries[`${ENTRY_PREFIX}live-1`]).toMatchObject({ post: "task_result", taskId: "t9", text: "Built." });
    expect(seen[2]).toEqual({ type: "summarized", summaryMessageId: "live-s" });
    mockPost((s, e) => source.emit(s, e), W({ id: "background", session_id: sid, content: "Completed elsewhere", request_id: "owned-background" }));
    expect(seen.at(-1)).toEqual({ type: "changed" });
    mockPost((s, e) => source.emit(s, e), W({ id: "foreign-background", session_id: "foreign", request_id: "foreign-request" }));
    expect(seen).toHaveLength(4);
    controller.abort();
    await running;
    MOCK_MESSAGES[sid].splice(keep);
  });
});

describe("mockHome", () => {
  it("puts the rich sample transcript after the newest wire page", async () => {
    const page = await mockHome(new MockSource()).page("s-native:jaeger");
    expect(page.turns.slice(0, 4).map((t) => t.turnId)).toEqual(["reply:old-4", `${ENTRY_PREFIX}post-r6`, `${ENTRY_PREFIX}post-h7`, `${ENTRY_PREFIX}post-t5`]);
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


describe("contract page owner identity", () => {
  it("preserves canonical specialist identity across newest and older pages", async () => {
    const get = vi.fn(async (path: string) => path.includes("/home")
      ? { session_id: "specialist-home", agent_id: "native:specialist", created: false }
      : path === "/v1/agents/specialist" ? { id: "native:specialist" } : { messages: [], next_before: null });
    const home = contractHome(get);
    const id = await home.home("specialist");
    expect((await home.page(id)).agentId).toBe("native:specialist");
    expect((await home.page(id, "older")).agentId).toBe("native:specialist");
    expect(get).toHaveBeenCalledTimes(4);
  });
  it("resolves explicit worker sessions through session identity and caches the binding", async () => {
    const get = vi.fn(async (path: string) => path === "/v1/sessions/worker"
      ? { session_id: "worker", agent_id: "native:worker" }
      : { messages: [], next_before: null });
    const home = contractHome(get);
    expect((await home.page("worker")).agentId).toBe("native:worker");
    expect((await home.page("worker", "older")).agentId).toBe("native:worker");
    expect(get.mock.calls.filter(([p]) => p === "/v1/sessions/worker")).toHaveLength(1);
  });
});

it("retains durable exchange correlation and terminal status across paged home reload", () => {
  const ui = fromWirePage('owned-home', { next_before: null, messages: [W({ id: 'owned-result', kind: 'handoff_result', status: 'completed', sender_agent_id: 'native:owned', content: 'owned result', links: { handoff_id: 'child', thread_handoff_id: 'root', reply_to_handoff_id: 'parent', origin_session_id: 'owned-home' } })] }, String);
  expect(ui.entries[ENTRY_PREFIX+'owned-result']).toMatchObject({ handoffId: 'child', threadId: 'root', replyTo: 'parent', originSessionId: 'owned-home', status: 'completed' });
});

it("rejects a foreign home and a stuck older-history cursor without creating a replacement", async () => {
 const home=contractHome(async path=> path.includes('/home') ? {agent_id:'other',session_id:'foreign'} : path.includes('/messages') ? {messages:[],next_before:'50'} : {agent_id:'a'});
 await expect(home.home('a')).rejects.toThrow('does not match');
 await expect(home.page('owned','50')).rejects.toThrow('did not advance');
});

it('preserves real admission identity across home snapshots instead of renaming message IDs as requests',()=>{
 const page=fromWirePage('owned-home',{next_before:null,messages:[W({id:22,role:'assistant',content:'Answer',request_id:'owned-request'}),W({id:21,role:'user',content:'Question',request_id:'owned-request'})]},String);
 expect(page.turns).toHaveLength(1);expect(page.turns[0]).toMatchObject({turnId:'owned-request',requestId:'owned-request',message:'Question'});
 const legacy=fromWirePage('owned-home',{next_before:null,messages:[W({id:17,role:'user',content:'Legacy'})]},String);
 expect(legacy.turns[0].turnId).toBe('17');expect(legacy.turns[0].requestId).toBeUndefined();
});
it('keeps incoming channel data in the continuous feed without inventing a result',()=>{
 const page=fromWirePage('owned-home',{next_before:null,messages:[W({id:'owned-incoming',kind:'channel_message',role:'user',content:'[telegram incoming] external data'})]},String);
 expect(page.entries).toEqual({});expect(page.turns).toHaveLength(1);
 expect(page.turns[0].message).toBe('[telegram incoming] external data');expect(page.turns[0].parts).toEqual([]);
});
