/** Read-only reconciliation. Never submits, cancels or retries execution. */
import type { RequestSnapshot } from "../api/source";
import type { ChatPart, ChatTurn, TurnState } from "./host";

export function requestOutcome(row: RequestSnapshot, onPart: (part: ChatPart) => void): TurnState | undefined {
  const states: Record<string, TurnState | undefined> = { completed: "complete", failed: "failed", cancelled: "cancelled", execution_unknown: "unknown" };
  const state = states[row.status];
  if (!state) return;
  const output = row.result?.output;
  // A streamed provisional item can contain the same bytes as the terminal
  // result. It is still not authoritative until this durable receipt arrives.
  // Always publish the explicit final item; applyPart replaces provisional
  // text by stable item identity and deduplicates an already-seen final.
  if (typeof output === "string") onPart({ kind: "markdownContent", text: output, role:"final", itemId:"final" });
  if (state === "unknown") onPart({ kind: "warning", message: "Execution outcome is unknown. This request has been preserved; it will not be resent." });
  if (state === "failed") onPart({ kind: "error", message: String(row.result?.error ?? row.result?.summary ?? "Request failed") });
  return state;
}

/** History load: a user turn with no reply reads its request receipt
 *  (read-only GET) so a failed or unknown turn shows its error and Retry after
 *  a reload instead of a silent gap. Never resends anything. */
export async function settleUnanswered(
  turns: ChatTurn[],
  lookup: ((requestId: string) => Promise<RequestSnapshot | undefined>) | undefined,
): Promise<ChatTurn[]> {
  if (!lookup) return turns;
  const open = turns.filter(t => t.requestId && t.message && t.parts.length === 0).slice(-20);
  await Promise.all(open.map(async (turn) => {
    try {
      const row = await lookup(String(turn.requestId));
      if (!row || row.request_id !== turn.requestId) return;
      const parts: ChatPart[] = [];
      const state = requestOutcome(row, (part) => parts.push(part));
      if (state && state !== "complete") { turn.parts = parts; turn.state = state; }
    } catch { /* leave the turn as loaded */ }
  }));
  return turns;
}
