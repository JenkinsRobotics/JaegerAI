/**
 * ChatPage — the real chat (Jenkins Robotics, 2026-10-30).
 *
 * Rebuilt from the mock "AppleApp" copy onto the app's own proven chat stack:
 * WebHost turn execution (chat/webHost.ts) + contractHome sessions
 * (chat/homeSession.ts) + MinimalChat rendering (chat/MinimalChat.tsx) — the
 * exact stack App.tsx runs with in production. No mock agents, no fabricated
 * responses; the gateway is data and the model is voice.
 *
 * Layout = the reference (ChatGPT): left rail is THIS conversation's history
 * (real SessionRows via the session list), search and New chat on top,
 * settings + agents at the footer. Persona switching lives in the Agents tab.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { SessionRow } from "../api/types";
import { WebHost } from "../chat/webHost";
import { ChatPane } from "../chat/ChatPane";
import {
  contractHome,
  fallbackHome,
  autoHome,
  httpGetJson,
  type HomeSessions,
  type HistoryRow,
} from "../chat/homeSession";
import { chatTitle, activityAt, shortTime } from "../agents/chats";
import { Search, Plus, Settings, Users, X } from "../components/Icons";

export interface ChatPageProps {
  source?: JaegerSource;
  /** Open another app window (settings / agents). */
  onOpenWindow?: (id: string) => void;
}

export function ChatPage({ source, onOpenWindow }: ChatPageProps) {
  // Host + home wiring: the exact trio App.tsx uses (WebHost + contract/auto home).
  const host = useMemo(() => {
    if (!source) return null;
    return new WebHost(source);
  }, [source]);
  const home: HomeSessions | undefined = useMemo(() => {
    if (!source) return undefined;
    if (source.homeSessions) return source.homeSessions({});
    const fallback = fallbackHome(source, {});
    return autoHome(contractHome(httpGetJson(), {}, source.stream.bind(source)), fallback);
  }, [source]);
  if (host) host.home = home;

  const [sessions, setSessions] = useState<HistoryRow[] | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | undefined>(undefined);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [starting, setStarting] = useState(false);

  // Real chat list: newest conversations first. Refreshes on a timer and when
  // the active chat changes (a sent turn bumps the session's activity time).
  const refreshSessions = useCallback(() => {
    if (!source?.sessions) {
      setSessionError("This gateway does not expose a session list yet.");
      return;
    }
    source.sessions()
      .then((rows: SessionRow[]) => {
        setSessions(
          rows
            .filter((r) => !r.archived)
            .sort((a, b) => (activityAt(b) ?? 0) - (activityAt(a) ?? 0))
            .map((r) => ({
              sessionId: r.session_id,
              title: chatTitle(r),
              updatedAt: activityAt(r),
              preview: r.last_message_preview ?? undefined,
              messageCount: r.message_count ?? undefined,
            })),
        );
        setSessionError(null);
      })
      .catch((e) => setSessionError(String((e as Error).message ?? e)));
  }, [source]);

  useEffect(() => {
    refreshSessions();
    const timer = window.setInterval(refreshSessions, 20_000);
    return () => window.clearInterval(timer);
  }, [refreshSessions, activeId]);

  // Open the newest conversation on first load so the pane is never blank
  // behind the composer. An empty list stays an honest empty state.
  useEffect(() => {
    if (!sessions || activeId) return;
    const first = sessions[0];
    if (first) setActiveId(first.sessionId);
  }, [sessions, activeId]);

  const openSession = useCallback(
    (id: string) => {
      setActiveId(id);
      setSearchOpen(false);
    },
    [],
  );

  const newChat = useCallback(async () => {
    if (!source?.createSession) return;
    setStarting(true);
    try {
      const created = await source.createSession({ title: "New chat" });
      refreshSessions();
      setActiveId(created.session_id);
      setSearchOpen(false);
    } catch (e) {
      setSessionError(String((e as Error).message ?? e));
    } finally {
      setStarting(false);
    }
  }, [source, refreshSessions]);

  const filtered = useMemo(() => {
    if (!sessions) return null;
    if (!query.trim()) return sessions.slice(0, 40);
    const q = query.toLowerCase();
    return sessions
      .filter((s) => s.title.toLowerCase().includes(q) || (s.preview ?? "").toLowerCase().includes(q))
      .slice(0, 40);
  }, [sessions, query]);

  return (
    <div className="cpage">
      <aside className="cpage-rail" aria-label="Chats">
        <div className="cpage-rail__header" data-aether-window-drag-region>
          <span className="jg-traffic-lights" aria-hidden="true"><i /><i /><i /></span>
        </div>

        <div className="cpage-rail__actions">
          <button type="button" className="cpage-rail__icon" aria-label="Search chats" title="Search" onClick={() => setSearchOpen((v) => !v)}>
            <Search size={15} />
          </button>
          <button
            type="button"
            className="cpage-rail__icon"
            aria-label="New chat"
            title="New chat"
            disabled={starting || !source?.createSession}
            onClick={() => void newChat()}
          >
            <Plus size={15} />
          </button>
          <button
            type="button"
            className="cpage-rail__icon cpage-rail__icon--end"
            aria-label="Manage agents"
            title="Agents"
            onClick={() => onOpenWindow?.("agents")}
          >
            <Users size={15} />
          </button>
        </div>

        {searchOpen && (
          <div className="cpage-rail__search">
            <input
              autoFocus
              type="text"
              placeholder="Search conversations…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setQuery("");
                  setSearchOpen(false);
                }
              }}
              aria-label="Search conversations"
            />
            {query && (
              <button type="button" className="cpage-rail__clear" aria-label="Clear search" onClick={() => setQuery("")}>
                <X size={12} />
              </button>
            )}
          </div>
        )}

        <div className="cpage-rail__scroll">
          {sessionError && <p className="cpage-rail__note">{sessionError}</p>}
          {sessions === null && !sessionError && <p className="cpage-rail__note">Reading conversations…</p>}
          {filtered !== null && filtered.length === 0 && !sessionError && (
            <p className="cpage-rail__note">{query ? "No conversations match." : "No conversations yet — start one."}</p>
          )}
          {filtered !== null && filtered.length > 0 && (
            <ul className="jg-chat-list" aria-label="Chat history">
              {filtered.map((row) => (
                <li key={row.sessionId}>
                  <button
                    type="button"
                    className={`jg-chat-row${row.sessionId === activeId ? " is-open" : ""}`}
                    aria-current={row.sessionId === activeId ? "page" : undefined}
                    title={row.preview || row.title}
                    onClick={() => openSession(row.sessionId)}
                  >
                    <span className="jg-chat-row__title">{row.title || "Untitled chat"}</span>
                    <span className="jg-chat-row__time">{shortTime(row.updatedAt)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="cpage-rail__footer">
          <button type="button" className="cpage-rail__foot-btn" onClick={() => onOpenWindow?.("nav")}>
            <Settings size={14} />
            <span>Settings</span>
          </button>
        </div>
      </aside>

      <main className="cpage-main">
        {!host ? (
          <p className="cpage-main__note">No Jaeger source is connected, so chatting is unavailable in this view.</p>
        ) : (
          <ChatPane host={host} sessionId={activeId} />
        )}
      </main>
    </div>
  );
}

export default ChatPage;