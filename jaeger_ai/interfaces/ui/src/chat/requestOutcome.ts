/** Read-only reconciliation. Never submits, cancels or retries execution. */
import type { RequestSnapshot } from "../api/source";
import type { ChatPart, TurnState } from "./host";

export function requestOutcome(row: Pick<RequestSnapshot, "status" | "result">, onPart: (part: ChatPart) => void): TurnState | undefined {
  const states: Record<string, TurnState | undefined> = { completed: "complete", failed: "failed", cancelled: "cancelled", execution_unknown: "unknown" };
  const state = states[row.status];
  if (!state) return;
  const output = row.result?.output;
  // A streamed provisional item can contain the same bytes as the terminal
  // result. It is still not authoritative until this durable receipt arrives.
  // Always publish the explicit final item; applyPart replaces provisional
  // text by stable item identity and deduplicates an already-seen final.
  // A failed/stopped/unknown receipt may have no final reply. Do not erase
  // provisional text already observed before interruption with an empty item.
  if (typeof output === "string" && (output.length > 0 || state === "complete")) onPart({ kind: "markdownContent", text: output, role:"final", itemId:"final" });
  if (state === "unknown") onPart({ kind: "warning", message: "Execution outcome is unknown. This request has been preserved; it will not be resent." });
  if (state === "failed") onPart({ kind: "error", message: String(row.result?.error ?? row.result?.summary ?? "Request failed") });
  return state;
}
