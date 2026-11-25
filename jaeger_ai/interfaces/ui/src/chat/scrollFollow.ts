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

export interface ScrollIntentInput {
  prevScrollTop: number;
  scrollTop: number;
  gap: number;
  thresholdPx: number;
  isProgrammatic: boolean;
  userInputActive: boolean;
  wasSticking: boolean;
}

/**
 * Deterministic auto-follow state transition that prevents scroll fighting on
 * desktop scrollbar drags and iOS Safari momentum scrolling (where scroll events
 * keep firing well after the 250 ms raw touch window expires).
 */
export function nextStickState(input: ScrollIntentInput): boolean {
  const near = input.gap < input.thresholdPx;
  if (input.isProgrammatic) return input.wasSticking;
  if (near) return true;
  // Any upward movement not caused by our own followNow() immediately yields
  // scroll control back to the reader — even during iOS momentum deceleration.
  if (input.scrollTop < input.prevScrollTop - 2) return false;
  if (input.userInputActive) return false;
  return input.wasSticking;
}
