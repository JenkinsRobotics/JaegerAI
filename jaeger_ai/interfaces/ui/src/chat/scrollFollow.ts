/* Scroll-follow helpers (Jenkins Robotics, 2026-10-17, original): how many messages arrived while the
 * reader was scrolled up, for the jump button's badge. */
import type { ChatTurn } from "./host";

/** User messages plus assistant text blocks with content: the "messages" a reader sees arrive. */
export function messageCount(turns: ChatTurn[]): number {
  let n = 0;
  for (const t of turns) {
    if (t.message) n += 1;
    for (const p of t.parts) if (p.kind === "markdownContent" && p.text.trim()) n += 1;
  }
  return n;
}

/** New messages since the reader left the bottom (baseline), 0 while following. */
export const unreadSince = (baseline: number | null, now: number): number => (baseline === null ? 0 : Math.max(0, now - baseline));

export const badge = (n: number): string => (n > 99 ? "99+" : String(n));
