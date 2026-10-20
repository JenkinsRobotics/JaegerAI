/* Gateway unread/read markers are authoritative. Local marks remain a fallback
 * for older sources that do not supply an unseen flag. */
const KEY = "jaeger.ui.agentSeen";

export function loadSeen(): Record<string, number> {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "{}") as Record<string, number>; } catch { return {}; }
}

export function markSeen(agentId: string, at = Date.now() / 1000): Record<string, number> {
  const seen = { ...loadSeen(), [agentId]: at };
  localStorage.setItem(KEY, JSON.stringify(seen));
  return seen;
}

/** Unread if there is activity newer than our local seen mark. Before this
 * device has a mark, fall back to the gateway's `unseen` flag. */
export function isUnread(agentId: string, lastActivityAt: number, seen: Record<string, number>, serverUnseen?: boolean): boolean {
  if (serverUnseen !== undefined) return serverUnseen;
  const mark = seen[agentId];
  if (mark === undefined) return Boolean(serverUnseen);
  return lastActivityAt > mark;
}
