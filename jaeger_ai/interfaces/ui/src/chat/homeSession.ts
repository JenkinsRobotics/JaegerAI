/* Home chats (Grok-style, decided 2026-10-18): each agent has ONE persistent chat. Older chats are
 * history (read-only); older messages are summarized, not dropped, and load in pages on scroll-up;
 * handoff and task results arrive as real messages in the chat.
 *
 * MinimalChat and the app only see `HomeSessions`. Three implementations:
 *  - contractHome: the gateway contract below (wire types + routes in one place);
 *  - fallbackHome: today's gateway (43438 dev): most recent chat for the agent, else create; pages are
 *    cut client-side from the one session load; no summaries or posts;
 *  - mockHome: contractHome over an in-memory wire fake + mock stream (dev mock / screenshots). */
import type { JaegerSource } from "../api/source";
import type { GatewayEvent, SessionMessage, SessionRow } from "../api/types";
import type { ChatSession, ChatTurn } from "./host";
import { messagesToTurns } from "./webHost";

// ---------------------------------------------------------------------------------------------
// Wire contract (the Gateway bot's proposal, forwarded 2026-10-18). Routes and shapes live only here.
// ---------------------------------------------------------------------------------------------

/** GET /v1/agents/{agent_id}/home → the agent's one home chat; `created` is true on the first call. */
export interface WireHome { session_id: string; agent_id: string; created: boolean }

export type WireKind = "message" | "summary" | "handoff_request" | "handoff_result" | "task_result";

/** One persisted message. */
export interface WireMessage {
  /** An integer on 417d8a0c; kept as string | number so ids never compare across types. */
  id: number | string;
  session_id: string;
  role: "user" | "assistant" | "system";
  kind: WireKind;
  /** The agent that posted it (handoff/task messages), as a plain id. */
  sender_agent_id?: string | null;
  /** Epoch seconds (an ISO string is accepted too). */
  created_at: number | string;
  content: string;
  status?: string;
  parts?: unknown[];
  links?: { handoff_id?: string; task_id?: string; child_session_id?: string; origin_session_id?: string; thread_handoff_id?: string; reply_to_handoff_id?: string };
  /** kind "summary" (role system): `content` summarizes `message_count` older messages. */
  summary?: { covers_from?: string | number | null; covers_to?: string | number | null; message_count: number };
}

/** GET /v1/sessions/{id}/messages?before=<message_id>&limit=50 → newest first; `next_before` is the
 * cursor for the next older page, null at the start of the chat. */
export interface WirePage { messages: WireMessage[]; next_before: number | string | null }

/** Live events on the session stream (GET /v1/sessions/{id}/stream). */
export interface WireMessageCreated { session_id: string; message: WireMessage }
export interface WireSessionSummarized { session_id: string; summary_message_id: number | string; covers_to?: string | number | null }

export const PAGE_LIMIT = 50;
export const PAGE_LIMIT_MAX = 200;
export const HOME_ROUTES = {
  home: (agentId: string) => `/v1/agents/${encodeURIComponent(agentId)}/home`,
  page: (sessionId: string, limit: number, before?: string) =>
    `/v1/sessions/${encodeURIComponent(sessionId)}/messages?${before ? `before=${encodeURIComponent(before)}&` : ""}limit=${Math.min(Math.max(1, limit), PAGE_LIMIT_MAX)}`,
  /** Older chats: the existing session list (last_message_preview, last_activity_at, last_event_id). */
  sessions: (agentId: string) => `/v1/sessions?agent_id=${encodeURIComponent(agentId)}`,
};
export const HOME_EVENT_MESSAGE = "message.created";
export const HOME_EVENT_SUMMARIZED = "session.summarized";

/** What the chat view does with a live event: show a new entry, or reload the newest page. */
export type HomeLiveEvent = { type: "entry"; page: HomePage } | { type: "summarized"; summaryMessageId: string };

export type GetJson = (path: string) => Promise<unknown>;

// ---------------------------------------------------------------------------------------------
// UI model
// ---------------------------------------------------------------------------------------------

export type HomeEntry =
  | { kind: "summary"; id: string; text: string; count: number; fromAt?: number; toAt?: number }
  | {
    kind: "post"; id: string; post: "handoff_request" | "handoff" | "task_result"; sender: { id: string; name: string }; text: string;
    title?: string; status?: string; threadId?: string; replyTo?: string; originSessionId?: string; handoffId?: string; taskId?: string; childSessionId?: string; createdAt?: number;
  };

/** A slice of a chat, oldest first. Summary and post messages are turns with no user text whose id
 * maps to an entry, so ordering, paging and unread counts stay turn-based. */
export interface HomePage {
  sessionId: string;
  title?: string;
  agentId?: string;
  turns: ChatTurn[];
  entries: Record<string, HomeEntry>;
  /** Cursor for the next older page; undefined at the start of the chat. */
  before?: string;
  lastEventId?: number;
}

export interface HistoryRow { sessionId: string; title: string; updatedAt?: number; preview?: string; messageCount?: number }

export interface HomeSessions {
  readonly mode: "contract" | "fallback" | "mock";
  /** The agent's home chat id. */
  home(agentId: string): Promise<string>;
  /** Newest page when `before` is undefined, else the page just older than it. */
  page(sessionId: string, before?: string): Promise<HomePage>;
  /** Older chats with this agent (never the home chat). */
  history(agentId: string): Promise<HistoryRow[]>;
  /** A whole older chat, read-only. */
  read(sessionId: string): Promise<HomePage>;
  /** Live summaries and posts for an open chat (contract/mock only); resolves when `signal` aborts. */
  live?(sessionId: string, on: (event: HomeLiveEvent) => void, signal: AbortSignal): Promise<void>;
}

export const ENTRY_PREFIX = "entry:";
export const entryOf = (page: Pick<HomePage, "entries">, turnId: string): HomeEntry | undefined => page.entries[turnId];

/** created_at / covers_* → epoch ms: numbers are seconds (or ms when huge), strings are ISO dates. */
export function toMs(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) return value > 1e12 ? value : value * 1000;
  if (typeof value === "string" && /\d{4}-\d{2}-\d{2}/.test(value)) { const ms = Date.parse(value); return Number.isFinite(ms) ? ms : undefined; }
  return undefined;
}

const POST: Record<string, "handoff_request" | "handoff" | "task_result"> = { handoff_request: "handoff_request", handoff_result: "handoff", task_result: "task_result" };

/** One wire message → the SessionMessage shape messagesToTurns already reads. */
const asSession = (m: WireMessage): SessionMessage => ({
  ...(m as unknown as SessionMessage), role: m.role, content: m.content, created_at: (toMs(m.created_at) ?? 0) / 1000,
  request_id: m.role === "user" ? String(m.id) : undefined,
});

/** Wire page (newest first) → UI page (oldest first). Ordinary messages group into turns as today
 * (messagesToTurns); a summary or post becomes its own entry turn in place. Turn ids come from
 * message ids, so pages never collide. */
export function fromWirePage(sessionId: string, page: WirePage, agentName: (id: string) => string): HomePage {
  const turns: ChatTurn[] = [];
  const entries: Record<string, HomeEntry> = {};
  let run: WireMessage[] = [];
  const flush = () => {
    if (!run.length) return;
    const ids = run.filter((m) => m.role === "user").map((m) => String(m.id));
    const mapped = messagesToTurns(run.map(asSession), agentName);
    // A run that opens with a reply gets a synthetic turn; name it after that message.
    mapped.forEach((t) => { if (!ids.includes(t.turnId)) t.turnId = `reply:${run[0].id}`; });
    turns.push(...mapped);
    run = [];
  };
  for (const m of [...page.messages].reverse()) {
    const kind = m.kind ?? "message";
    if (kind === "message") { run.push(m); continue; }
    flush();
    const turnId = ENTRY_PREFIX + m.id;
    const createdAt = toMs(m.created_at);
    turns.push({ turnId, message: "", parts: [], state: "complete", createdAt });
    if (kind === "summary") {
      entries[turnId] = { kind: "summary", id: String(m.id), text: m.content ?? "", count: m.summary?.message_count ?? 0,
        fromAt: toMs(m.summary?.covers_from), toAt: toMs(m.summary?.covers_to) };
    } else {
      const id = m.sender_agent_id ?? "";
      entries[turnId] = {
        kind: "post", id: String(m.id), post: POST[kind] ?? "task_result", sender: { id, name: agentName(id) }, text: m.content ?? "",
        status: m.status, threadId: m.links?.thread_handoff_id ?? m.links?.handoff_id, replyTo: m.links?.reply_to_handoff_id, originSessionId: m.links?.origin_session_id, handoffId: m.links?.handoff_id, taskId: m.links?.task_id, childSessionId: m.links?.child_session_id, createdAt,
      };
    }
  }
  flush();
  return { sessionId, turns, entries, before: page.next_before != null ? String(page.next_before) : undefined };
}

const historyRow = (r: SessionRow): HistoryRow => ({
  sessionId: r.session_id, title: r.title || "Untitled", updatedAt: (r.last_activity_at ?? r.updated_at) ? (r.last_activity_at ?? r.updated_at)! * 1000 : undefined,
  preview: r.last_message_preview, messageCount: r.message_count,
});

export interface HomeOptions {
  agentName?: (id: string) => string;
  pageSize?: number;
  /** The SSE cursor for a session the chat just loaded (WebHost.noteCursor). */
  onCursor?: (sessionId: string, eventId: number) => void;
}

/** Session stream subscription (JaegerSource.stream). */
export type HomeStream = (sessionId: string, cursor: number | undefined, onEvent: (event: GatewayEvent) => void, signal: AbortSignal) => Promise<void>;

const rowsOf = (data: unknown): SessionRow[] => (Array.isArray(data) ? data : (data as { sessions?: SessionRow[] })?.sessions ?? []) as SessionRow[];

/** The gateway contract. `stream` enables live posts and summaries. */
export function contractHome(getJson: GetJson, opts: HomeOptions = {}, stream?: HomeStream): HomeSessions {
  const name = opts.agentName ?? ((id: string) => id);
  const limit = opts.pageSize ?? PAGE_LIMIT;
  const homes = new Map<string, string>(); // agent → home session
  const agentOf = new Map<string, string>(); // home session → agent
  const page = async (sessionId: string, before?: string) => {
    // Message pages carry content, not the identity of the conversation owner.
    // Preserve the canonical home binding; explicit worker/history links use
    // the existing session contract rather than falling back to the lead.
    if (!agentOf.has(sessionId)) {
      const detail = await getJson(`/v1/sessions/${encodeURIComponent(sessionId)}`) as SessionRow;
      if (detail.agent_id) agentOf.set(sessionId, detail.agent_id);
    }
    return { ...fromWirePage(sessionId, (await getJson(HOME_ROUTES.page(sessionId, limit, before))) as WirePage, name), agentId: agentOf.get(sessionId) };
  };
  const rows = async (agentId: string) => rowsOf(await getJson(HOME_ROUTES.sessions(agentId)));
  return {
    mode: "contract",
    async home(agentId) {
      const wire = (await getJson(HOME_ROUTES.home(agentId))) as WireHome;
      homes.set(agentId, wire.session_id);
      agentOf.set(wire.session_id, wire.agent_id);
      return wire.session_id;
    },
    page,
    async history(agentId) {
      const home = homes.get(agentId) ?? (await this.home(agentId));
      return (await rows(agentId)).filter((r) => !r.archived && r.session_id !== home)
        .sort((a, b) => (b.last_activity_at ?? 0) - (a.last_activity_at ?? 0)).map(historyRow);
    },
    async read(sessionId) {
      // Whole chat: walk pages back to the start.
      let cur = await page(sessionId);
      const all = { ...cur, turns: [...cur.turns], entries: { ...cur.entries } };
      while (cur.before) {
        cur = await page(sessionId, cur.before);
        all.turns = [...cur.turns, ...all.turns];
        Object.assign(all.entries, cur.entries);
      }
      return { ...all, before: undefined };
    },
    live: stream && (async (sessionId, on, signal) => {
      // Start at the session's current cursor (from the session list) so nothing old replays.
      const agentId = agentOf.get(sessionId);
      const row = agentId ? (await rows(agentId).catch(() => [])).find((r) => r.session_id === sessionId) : undefined;
      if (typeof row?.last_event_id === "number") opts.onCursor?.(sessionId, row.last_event_id);
      await stream(sessionId, row?.last_event_id, (event) => {
        const payload = (event.payload ?? event) as Record<string, unknown>;
        if (event.event === HOME_EVENT_MESSAGE) {
          const msg = (payload as unknown as WireMessageCreated).message;
          // Ordinary messages arrive through the turn stream already; posts and summaries don't.
          if (msg && msg.session_id === sessionId && msg.kind && msg.kind !== "message") on({ type: "entry", page: fromWirePage(sessionId, { messages: [msg], next_before: null }, name) });
        } else if (event.event === HOME_EVENT_SUMMARIZED) {
          const sum = payload as unknown as WireSessionSummarized;
          if (sum.session_id === sessionId) on({ type: "summarized", summaryMessageId: String(sum.summary_message_id) });
        }
      }, signal).catch((error: unknown) => { if (!signal.aborted) throw error; });
    }),
  };
}

/** Same-origin JSON GET for contractHome (the dev proxy / WebUI adds the caller token). */
export const httpGetJson = (base = ""): GetJson => async (path) => {
  const response = await fetch(`${base}${path}`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
  const body = await response.json().catch(() => undefined);
  if (!response.ok) {
    const error = (body as { error?: string } | undefined)?.error;
    // routeMissing: a 404/405 without the gateway's JSON error body (an older gateway has no such route).
    throw Object.assign(new Error(error ?? `${response.status} ${response.statusText}`),
      { status: response.status, routeMissing: (response.status === 404 || response.status === 405) && !error });
  }
  return body ?? {};
};

/** The landed contract (417d8a0c) by default; a gateway without GET /v1/agents/{id}/home falls back to
 * fallbackHome for the rest of the session (feature-detect on the first home lookup). An unknown agent's
 * 404 carries a JSON error and is passed through, not treated as a missing route. */
export function autoHome(contract: HomeSessions, fallback: HomeSessions): HomeSessions {
  let use: HomeSessions | undefined;
  const pick = async (agentId?: string): Promise<HomeSessions> => {
    if (use) return use;
    if (!agentId) return contract;
    try { await contract.home(agentId); use = contract; } catch (error) {
      if ((error as { routeMissing?: boolean }).routeMissing) use = fallback; else throw error;
    }
    return use;
  };
  return {
    get mode() { return (use ?? contract).mode; },
    async home(agentId) { return (await pick(agentId)).home(agentId); },
    async page(sessionId, before) { return (use ?? contract).page(sessionId, before); },
    async history(agentId) { return (await pick(agentId)).history(agentId); },
    async read(sessionId) { return (use ?? contract).read(sessionId); },
    live(sessionId, on, signal) { const h = use ?? contract; return h.live ? h.live(sessionId, on, signal) : Promise.resolve(); },
  };
}

const CHOSEN_KEY = "jaeger.ui.chosen-chat";
function loadChosen(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(CHOSEN_KEY) ?? "{}") as Record<string, string>; } catch { return {}; }
}
const activity = (r: SessionRow) => r.last_activity_at ?? r.updated_at ?? r.created_at ?? 0;
const hasMessages = (r: SessionRow) => (r.message_count ?? 0) > 0 || Boolean(r.last_message_preview);

/** Today's gateway: the home chat is the one this device used last (if still live), else the most
 * recent chat with messages, else any open one, else a new one. One lookup per agent at a time. */
export function fallbackHome(source: JaegerSource, opts: HomeOptions = {}): HomeSessions {
  const name = opts.agentName ?? ((id: string) => id);
  const size = opts.pageSize ?? 30;
  const pending = new Map<string, Promise<string>>();
  const loaded = new Map<string, Promise<{ session: ChatSession; lastEventId?: number }>>();
  const homeIds = new Map<string, string>();
  const load = (sessionId: string, fresh: boolean) => {
    if (fresh || !loaded.has(sessionId)) {
      loaded.set(sessionId, source.session(sessionId).then((d) => ({
        session: { id: sessionId, title: d.title ?? "Untitled", agentId: d.agent_id ?? undefined, turns: messagesToTurns(d.messages, name) },
        lastEventId: d.last_event_id,
      })));
    }
    return loaded.get(sessionId)!;
  };
  const slice = async (sessionId: string, before?: string): Promise<HomePage> => {
    const { session, lastEventId } = await load(sessionId, before === undefined);
    if (before === undefined && typeof lastEventId === "number") opts.onCursor?.(sessionId, lastEventId);
    const end = before === undefined ? session.turns.length : Number(before);
    const start = Math.max(0, end - size);
    return { sessionId, title: session.title, agentId: session.agentId, turns: session.turns.slice(start, end), entries: {},
      before: start > 0 ? String(start) : undefined, lastEventId };
  };
  return {
    mode: "fallback",
    home(agentId) {
      let found = pending.get(agentId);
      if (!found) {
        found = source.sessions({ agent_id: agentId }).then(async (rows) => {
          const open = rows.filter((r) => !r.archived).sort((a, b) => activity(b) - activity(a));
          const remembered = loadChosen()[agentId];
          const pick = open.find((r) => r.session_id === remembered) ?? open.find(hasMessages) ?? open[0];
          const id = pick?.session_id ?? (await source.createSession({ agent_id: agentId })).session_id;
          localStorage.setItem(CHOSEN_KEY, JSON.stringify({ ...loadChosen(), [agentId]: id }));
          homeIds.set(agentId, id);
          return id;
        }).finally(() => pending.delete(agentId));
        pending.set(agentId, found);
      }
      return found;
    },
    page: slice,
    async history(agentId) {
      const home = homeIds.get(agentId) ?? (await this.home(agentId));
      const rows = await source.sessions({ agent_id: agentId });
      return rows.filter((r) => !r.archived && r.session_id !== home && hasMessages(r)).sort((a, b) => activity(b) - activity(a)).map(historyRow);
    },
    async read(sessionId) {
      const { session, lastEventId } = await load(sessionId, true);
      return { sessionId, title: session.title, agentId: session.agentId, turns: session.turns, entries: {}, lastEventId };
    },
  };
}
