/* DEV ONLY (loaded with the mock source): an in-memory fake of the PROVISIONAL home-chat wire
 * contract (chat/homeSession.ts), so the mock exercises the same mapping as the real gateway will.
 * The newest page of a chat also carries the rich sample transcript (every ChatPart kind). */
import { contractHome, type GetJson, type HomeOptions, type HomeSessions, type WireMessage, type WirePage } from "../chat/homeSession";
import type { JaegerSource } from "./source";
import type { SessionRow } from "./types";

const now = () => Date.now() / 1000;
const ago = (minutes: number) => now() - minutes * 60;
const LEAD_HOME = "s-native:jaeger";

const msg = (id: string, role: "user" | "assistant", content: string, minutes: number): WireMessage =>
  ({ id, role, content, timestamp: ago(minutes) });

/** Session → pages, newest first. */
export const MOCK_PAGES: Record<string, WirePage[]> = {
  [LEAD_HOME]: [
    {
      has_more: true, before: "p2", last_event_id: 0,
      messages: [
        {
          id: "post-h7", kind: "handoff_result", role: "assistant", timestamp: ago(4),
          sender: { agent_id: "agent:gateway-webui", name: "Jaeger Gateway & WebUI" }, handoff_id: "h7", title: "Home-chat endpoints", status: "done",
          content: "The home-chat endpoints are up on the test gateway: one home chat per agent, paged history and summary messages. The contract is in the PR description.",
          links: [{ label: "PR #412", url: "https://example.invalid/jaeger/pull/412" }],
        },
        {
          id: "post-t5", kind: "task_result", role: "assistant", timestamp: ago(3),
          sender: { agent_id: "agent:mac-app", name: "Mac App" }, task_id: "t5", title: "Sign and notarize the Mac shell", status: "failed",
          content: "Notarization stopped: the signing identity isn't in the test keychain. Nothing was uploaded.",
          links: [],
        },
      ],
    },
    {
      has_more: false, before: null,
      messages: [
        {
          id: "sum-1", kind: "summary", role: "system", timestamp: ago(60 * 26),
          summary: { covers_count: 48, from_ts: ago(60 * 24 * 6), to_ts: ago(60 * 26),
            text: "Planned the UI rebuild with four specialists. Agreed the sidebar shows agents, not chats; the Mac shell hosts the new main screen; IDE Chat freezes the chat seam. Open: gateway ownership after the restart." },
        },
        msg("old-1", "user", "Where did we leave the gateway restart?", 60 * 25),
        msg("old-2", "assistant", "It's waiting on the owner file. Agents View will check it once the new Mac app is the owner.", 60 * 25 - 1),
        msg("old-3", "user", "Okay. Keep the old app closed until then.", 60 * 24),
        msg("old-4", "assistant", "Will do. I'll tell you when it's safe.", 60 * 24 - 1),
      ],
    },
  ],
  "s-old-1": [{ has_more: false, messages: [msg("o1a", "user", "Draft the rollout note for the new sidebar.", 60 * 24 * 9), msg("o1b", "assistant", "Here's a short note: the sidebar now lists agents; each opens its own chat. Your old chats are under History.", 60 * 24 * 9 - 1)] }],
  "s-old-2": [{ has_more: false, messages: [msg("o2a", "user", "What broke in last night's build?", 60 * 24 * 12), msg("o2b", "assistant", "A stale lockfile. SWE regenerated it and the build is green again.", 60 * 24 * 12 - 2)] }],
};

export const MOCK_HISTORY: Record<string, SessionRow[]> = {
  "native:jaeger": [
    { session_id: "s-old-1", title: "Sidebar rollout note", agent_id: "native:jaeger", last_activity_at: ago(60 * 24 * 9), message_count: 2, last_message_preview: "Here's a short note: the sidebar now lists agents…" },
    { session_id: "s-old-2", title: "Overnight build failure", agent_id: "native:jaeger", last_activity_at: ago(60 * 24 * 12), message_count: 2, last_message_preview: "A stale lockfile. SWE regenerated it…" },
  ],
};

/** GetJson over the fixtures, answering exactly the provisional routes. */
export function mockHomeWire(): GetJson {
  return async (path) => {
    const url = new URL(path, "http://mock.invalid");
    const home = url.pathname.match(/^\/v1\/agents\/([^/]+)\/home$/);
    if (home) { const agent = decodeURIComponent(home[1]); return { session_id: `s-${agent}`, agent_id: agent }; }
    const hist = url.pathname.match(/^\/v1\/agents\/([^/]+)\/history$/);
    if (hist) return { sessions: MOCK_HISTORY[decodeURIComponent(hist[1])] ?? [] };
    const page = url.pathname.match(/^\/v1\/sessions\/([^/]+)\/messages$/);
    if (page) {
      const pages = MOCK_PAGES[decodeURIComponent(page[1])] ?? [{ has_more: false, messages: [] }];
      const before = url.searchParams.get("before");
      const index = before ? pages.findIndex((_p, i) => pages[i - 1]?.before === before) : 0;
      return pages[Math.max(0, index)];
    }
    throw new Error(`mock: no route ${path}`);
  };
}

export function mockHome(source: JaegerSource, opts: HomeOptions = {}): HomeSessions {
  const base = contractHome(mockHomeWire(), opts);
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
