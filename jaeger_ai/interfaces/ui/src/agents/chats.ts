/* An agent's chats in the sidebar (Grok Bot: every chat keeps a row, a fresh
 * chat never hides the old one). Pure helpers + the per-agent loader. */
import { useCallback, useEffect, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { SessionRow } from "../api/types";

const GENERIC_TITLES = new Set(["", "new chat", "new conversation", "untitled"]);
const TITLE_CHARS = 48;

const activityAt = (row: SessionRow) => row.last_activity_at ?? row.updated_at ?? row.created_at ?? 0;

/** Not archived; empty chats only when open (an empty "New chat" is not history). */
export function visibleChats(rows: SessionRow[], openId?: string): SessionRow[] {
  return rows
    .filter((r) => !r.archived && ((r.message_count ?? 0) > 0 || Boolean(r.last_message_preview) || r.session_id === openId))
    .sort((a, b) => activityAt(b) - activityAt(a));
}

export function chatTitle(row: SessionRow): string {
  const title = (row.title ?? "").trim();
  if (!GENERIC_TITLES.has(title.toLowerCase())) return title;
  const preview = (row.last_message_preview ?? "").replace(/\s+/g, " ").trim();
  if (preview) return preview.length > TITLE_CHARS ? `${preview.slice(0, TITLE_CHARS - 1)}…` : preview;
  return (row.message_count ?? 0) > 0 ? "Chat" : "New chat";
}

/** "now", "5m", "3h", "Yesterday", "Oct 15". Epoch seconds in. */
export function shortTime(seconds: number | undefined, now = Date.now()): string {
  if (!seconds) return "";
  const ms = seconds * 1000;
  const diff = Math.max(0, now - ms);
  if (diff < 60_000) return "now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m`;
  const day = (t: number) => new Date(new Date(t).toDateString()).getTime();
  const days = Math.round((day(now) - day(ms)) / 86_400_000);
  if (days === 0) return `${Math.floor(diff / 3_600_000)}h`;
  if (days === 1) return "Yesterday";
  return new Date(ms).toLocaleDateString([], { month: "short", day: "numeric" });
}

/** The selected agent's chats, reloaded when `version` changes (new chat,
 * rename, archive) and on the roster poll. */
export function useAgentChats(source: JaegerSource, agentId: string | undefined, version: number) {
  const [rows, setRows] = useState<SessionRow[]>([]);
  const load = useCallback(() => {
    if (!agentId) { setRows([]); return () => {}; }
    let live = true;
    source.sessions({ agent_id: agentId }).then((r) => { if (live) setRows(r); }, () => { if (live) setRows([]); });
    return () => { live = false; };
  }, [source, agentId]);
  useEffect(() => load(), [load, version]);
  return rows;
}

export { activityAt };
