/* Home chats (Grok-style, decided 2026-10-18): each agent has ONE persistent chat. Older chats are
 * history (read-only); older messages are summarized, not dropped, and load in pages on scroll-up;
 * handoff and task results arrive as real messages in the chat.
 *
 * MinimalChat and the app only see `HomeSessions`. Three implementations:
 *  - contractHome: the PROVISIONAL gateway contract below (wire types + routes in one place, so the
 *    real contract is a small diff here and nowhere else);
 *  - fallbackHome: today's gateway (43438 dev): most recent chat for the agent, else create; pages are
 *    cut client-side from the one session load; no summaries or posts;
 *  - mockHome: contractHome over an in-memory wire fake (dev mock / screenshots). */
import type { JaegerSource } from "../api/source";
import type { SessionMessage, SessionRow } from "../api/types";
import type { ChatSession, ChatTurn } from "./host";
import { messagesToTurns } from "./webHost";

// ---------------------------------------------------------------------------------------------
// PROVISIONAL wire contract (diff against the Gateway bot's answer).
// ---------------------------------------------------------------------------------------------

/** GET /v1/agents/{agent_id}/home → the agent's one home chat (created on first call). */
export interface WireHome { session_id: string; agent_id: string; title?: string; created?: boolean; last_event_id?: number }

/** One persisted message. `kind` absent or "message" = an ordinary user/assistant message. */
export interface WireMessage extends SessionMessage {
  id: string;
  kind?: "message" | "summary" | "handoff_result" | "task_result";
  /** kind "summary": stands in for `covers_count` older messages that were summarized. */
  summary?: { text: string; covers_count: number; from_ts?: number; to_ts?: number };
  /** kind handoff_result / task_result: who posted it. */
  sender?: { agent_id: string; name?: string };
  handoff_id?: string;
  task_id?: string;
  title?: string;
  status?: "done" | "failed" | "cancelled" | string;
  links?: Array<{ label: string; url: string }>;
}

/** GET /v1/sessions/{id}/messages?limit=N[&before=<cursor>] → newest-last page. */
export interface WirePage { messages: WireMessage[]; has_more: boolean; before?: string | null; last_event_id?: number }

/** GET /v1/agents/{agent_id}/history → the agent's older chats (not the home chat), newest first. */
export interface WireHistory { sessions: SessionRow[] }

export const HOME_ROUTES = {
  home: (agentId: string) => `/v1/agents/${encodeURIComponent(agentId)}/home`,
  page: (sessionId: string, limit: number, before?: string) =>
    `/v1/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}${before ? `&before=${encodeURIComponent(before)}` : ""}`,
  history: (agentId: string) => `/v1/agents/${encodeURIComponent(agentId)}/history`,
};
/** Live stream (same session SSE): `message.created` carries a WireMessage (summaries, posts). */
export const HOME_EVENT_MESSAGE = "message.created";

export type GetJson = (path: string) => Promise<unknown>;

// ---------------------------------------------------------------------------------------------
// UI model
// ---------------------------------------------------------------------------------------------

export type HomeEntry =
  | { kind: "summary"; id: string; text: string; count: number; fromAt?: number; toAt?: number }
  | {
    kind: "post"; id: string; post: "handoff" | "task_result"; sender: { id: string; name: string }; text: string;
    title?: string; status?: string; handoffId?: string; taskId?: string; links: Array<{ label: string; url: string }>; createdAt?: number;
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
}

export const ENTRY_PREFIX = "entry:";
export const entryOf = (page: Pick<HomePage, "entries">, turnId: string): HomeEntry | undefined => page.entries[turnId];

const seconds = (m: Pick<SessionMessage, "timestamp" | "created_at">) => {
  const s = Number(m.timestamp ?? m.created_at);
  return Number.isFinite(s) && s > 0 ? s * 1000 : undefined;
};

/** Wire page → UI page. Ordinary messages group into turns as today (messagesToTurns); a summary or
 * post becomes its own entry turn in place. Turn ids come from message ids, so pages never collide. */
export function fromWirePage(sessionId: string, page: WirePage, agentName: (id: string) => string): HomePage {
  const turns: ChatTurn[] = [];
  const entries: Record<string, HomeEntry> = {};
  let run: WireMessage[] = [];
  const flush = () => {
    if (!run.length) return;
    const ids = run.filter((m) => m.role === "user").map((m) => m.request_id ?? m.id);
    const mapped = messagesToTurns(run.map((m) => (m.role === "user" ? { ...m, request_id: m.request_id ?? m.id } : m)), agentName);
    // A run that opens with a reply gets a synthetic turn; name it after that message.
    mapped.forEach((t) => { if (!ids.includes(t.turnId)) t.turnId = `reply:${run[0].id}`; });
    turns.push(...mapped);
    run = [];
  };
  for (const m of page.messages) {
    const kind = m.kind ?? "message";
    if (kind === "message") { run.push(m); continue; }
    flush();
    const turnId = ENTRY_PREFIX + m.id;
    const createdAt = seconds(m);
    turns.push({ turnId, message: "", parts: [], state: "complete", createdAt });
    if (kind === "summary") {
      entries[turnId] = { kind: "summary", id: m.id, text: m.summary?.text ?? m.content ?? "", count: m.summary?.covers_count ?? 0,
        fromAt: m.summary?.from_ts ? m.summary.from_ts * 1000 : undefined, toAt: m.summary?.to_ts ? m.summary.to_ts * 1000 : undefined };
    } else {
      const id = m.sender?.agent_id ?? "";
      entries[turnId] = {
        kind: "post", id: m.id, post: kind === "handoff_result" ? "handoff" : "task_result",
        sender: { id, name: m.sender?.name || agentName(id) }, text: m.content ?? "", title: m.title, status: m.status,
        handoffId: m.handoff_id, taskId: m.task_id, links: m.links ?? [], createdAt,
      };
    }
  }
  flush();
  return { sessionId, turns, entries, before: page.has_more && page.before ? page.before : undefined, lastEventId: page.last_event_id };
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

/** The provisional gateway contract. */
export function contractHome(getJson: GetJson, opts: HomeOptions = {}): HomeSessions {
  const name = opts.agentName ?? ((id: string) => id);
  const limit = opts.pageSize ?? 30;
  const page = async (sessionId: string, before?: string) => {
    const wire = (await getJson(HOME_ROUTES.page(sessionId, limit, before))) as WirePage;
    const mapped = fromWirePage(sessionId, wire, name);
    if (!before && typeof mapped.lastEventId === "number") opts.onCursor?.(sessionId, mapped.lastEventId);
    return mapped;
  };
  return {
    mode: "contract",
    home: async (agentId) => ((await getJson(HOME_ROUTES.home(agentId))) as WireHome).session_id,
    page,
    history: async (agentId) => ((await getJson(HOME_ROUTES.history(agentId))) as WireHistory).sessions.filter((r) => !r.archived).map(historyRow),
    read: async (sessionId) => {
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
  };
}

/** Same-origin JSON GET for contractHome (the dev proxy / WebUI adds the caller token). */
export const httpGetJson = (base = ""): GetJson => async (path) => {
  const response = await fetch(`${base}${path}`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((body as { error?: string }).error ?? `${response.status} ${response.statusText}`);
  return body;
};

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
