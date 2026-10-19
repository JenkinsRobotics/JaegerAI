/* DEV ONLY (loaded with the mock source): an in-memory fake of the home-chat wire contract
 * (chat/homeSession.ts), so the mock exercises the same mapping, paging and live events as the real
 * gateway. The newest page of a chat also carries the rich sample transcript (every ChatPart kind). */
import { contractHome, HOME_EVENT_MESSAGE, HOME_EVENT_SUMMARIZED, type GetJson, type HomeOptions, type HomeSessions, type HomeStream, type WireMessage } from "../chat/homeSession";
import type { JaegerSource } from "./source";
import type { SessionRow } from "./types";

const now = () => Date.now() / 1000;
const ago = (minutes: number) => now() - minutes * 60;
const LEAD_HOME = "s-native:jaeger";

const msg = (session_id: string, id: string, role: "user" | "assistant", content: string, minutes: number): WireMessage =>
  ({ id, session_id, role, kind: "message", content, created_at: ago(minutes) });

/** Session → all messages, OLDEST first (the route serves them newest first, paged by message id). */
export const MOCK_MESSAGES: Record<string, WireMessage[]> = {
  [LEAD_HOME]: [
    {
      id: "sum-1", session_id: LEAD_HOME, role: "system", kind: "summary", created_at: ago(60 * 26),
      summary: { covers_from: ago(60 * 24 * 6), covers_to: ago(60 * 26), message_count: 48 },
      content: "Planned the UI rebuild with four specialists. Agreed the sidebar shows agents, not chats; the Mac shell hosts the new main screen; IDE Chat freezes the chat seam. Open: gateway ownership after the restart.",
    },
    msg(LEAD_HOME, "old-1", "user", "Where did we leave the gateway restart?", 60 * 25),
    msg(LEAD_HOME, "old-2", "assistant", "It's waiting on the owner file. Agents View will check it once the new Mac app is the owner.", 60 * 25 - 1),
    msg(LEAD_HOME, "old-3", "user", "Okay. Keep the old app closed until then.", 60 * 24),
    msg(LEAD_HOME, "old-4", "assistant", "Will do. I'll tell you when it's safe.", 60 * 24 - 1),
    {
      id: "post-r6", session_id: LEAD_HOME, role: "assistant", kind: "handoff_request", created_at: ago(9),
      sender_agent_id: "native:jaeger", links: { handoff_id: "h7", child_session_id: "s-agent:gateway-webui" },
      content: "Asked Jaeger Gateway & WebUI to put up the home-chat endpoints on the test gateway.",
    },
    {
      id: "post-h7", session_id: LEAD_HOME, role: "assistant", kind: "handoff_result", created_at: ago(4),
      sender_agent_id: "agent:gateway-webui", links: { handoff_id: "h7", child_session_id: "s-agent:gateway-webui" },
      content: "The home-chat endpoints are up on the test gateway: one home chat per agent, paged history and summary messages. The contract is in [PR #412](https://example.invalid/jaeger/pull/412).",
    },
    {
      id: "post-t5", session_id: LEAD_HOME, role: "assistant", kind: "task_result", created_at: ago(3),
      sender_agent_id: "agent:mac-app", links: { task_id: "t5" },
      content: "Notarization stopped: the signing identity isn't in the test keychain. Nothing was uploaded.",
    },
  ],
  "s-old-1": [msg("s-old-1", "o1a", "user", "Draft the rollout note for the new sidebar.", 60 * 24 * 9), msg("s-old-1", "o1b", "assistant", "Here's a short note: the sidebar now lists agents; each opens its own chat. Your old chats are under History.", 60 * 24 * 9 - 1)],
  "s-old-2": [msg("s-old-2", "o2a", "user", "What broke in last night's build?", 60 * 24 * 12), msg("s-old-2", "o2b", "assistant", "A stale lockfile. SWE regenerated it and the build is green again.", 60 * 24 * 12 - 2)],
};

/** GET /v1/sessions?agent_id= rows (the home chat is listed too; history leaves it out). */
export const MOCK_SESSIONS: Record<string, SessionRow[]> = {
  "native:jaeger": [
    { session_id: LEAD_HOME, title: "Jaeger", agent_id: "native:jaeger", last_activity_at: ago(3), message_count: 9, last_message_preview: "Notarization stopped…", last_event_id: 0 },
    { session_id: "s-old-1", title: "Sidebar rollout note", agent_id: "native:jaeger", last_activity_at: ago(60 * 24 * 9), message_count: 2, last_message_preview: "Here's a short note: the sidebar now lists agents…" },
    { session_id: "s-old-2", title: "Overnight build failure", agent_id: "native:jaeger", last_activity_at: ago(60 * 24 * 12), message_count: 2, last_message_preview: "A stale lockfile. SWE regenerated it…" },
  ],
};

/** GetJson over the fixtures, answering exactly the contract routes. A page holds at most `pageSize`
 * messages (default 4, below the route's limit) so the mock's newest page stops short of the summary. */
export function mockHomeWire(pageSize = 4): GetJson {
  return async (path) => {
    const url = new URL(path, "http://mock.invalid");
    const home = url.pathname.match(/^\/v1\/agents\/([^/]+)\/home$/);
    if (home) { const agent = decodeURIComponent(home[1]); return { session_id: `s-${agent}`, agent_id: agent, created: !MOCK_MESSAGES[`s-${agent}`] }; }
    if (url.pathname === "/v1/sessions") return { sessions: MOCK_SESSIONS[url.searchParams.get("agent_id") ?? ""] ?? [] };
    const page = url.pathname.match(/^\/v1\/sessions\/([^/]+)\/messages$/);
    if (page) {
      const all = [...(MOCK_MESSAGES[decodeURIComponent(page[1])] ?? [])].reverse(); // newest first
      const before = url.searchParams.get("before");
      const start = before ? all.findIndex((m) => m.id === before) + 1 : 0;
      const limit = Math.min(Number(url.searchParams.get("limit") ?? 50), pageSize);
      const messages = all.slice(start, start + limit);
      return { messages, next_before: start + limit < all.length ? messages[messages.length - 1].id : null };
    }
    throw new Error(`mock: no route ${path}`);
  };
}

type Emit = (sessionId: string, event: { event: string; payload: Record<string, unknown> }) => void;

/** Post a message into a mock chat the way the gateway would: store it, announce message.created (and
 * session.summarized for a summary). */
export function mockPost(emit: Emit, message: WireMessage) {
  (MOCK_MESSAGES[message.session_id] ??= []).push(message);
  emit(message.session_id, { event: HOME_EVENT_MESSAGE, payload: { session_id: message.session_id, message } });
  if (message.kind === "summary") {
    emit(message.session_id, { event: HOME_EVENT_SUMMARIZED, payload: { session_id: message.session_id, summary_message_id: message.id, covers_to: message.summary?.covers_to ?? null } });
  }
}

export function mockHome(source: JaegerSource, opts: HomeOptions = {}): HomeSessions {
  const base = contractHome(mockHomeWire(), opts, source.stream.bind(source) as HomeStream);
  return {
    ...base,
    mode: "mock",
    async page(sessionId, before) {
      const page = await base.page(sessionId, before);
      const rich = before ? undefined : source.transcript?.(sessionId);
      return rich ? { ...page, title: rich.title, agentId: rich.agentId, turns: [...page.turns, ...structuredClone(rich.turns)] } : page;
    },
  };
}
