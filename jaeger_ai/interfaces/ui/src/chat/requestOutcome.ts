/** Read-only reconciliation. Never submits, cancels or retries execution. */
import type { RequestSnapshot } from "../api/source";
import type { ChatPart, TurnState } from "./host";

export function requestOutcome(row: RequestSnapshot, onPart: (part: ChatPart) => void, streamed = ""): TurnState | undefined {
  const states: Record<string, TurnState | undefined> = { completed: "complete", failed: "failed", cancelled: "cancelled", execution_unknown: "unknown" };
  const state = states[row.status];
  if (!state) return;
  const output = row.result?.output;
  if (typeof output === "string" && output.startsWith(streamed) && output.length > streamed.length) onPart({ kind: "markdownContent", text: output.slice(streamed.length) });
  if (state === "unknown") onPart({ kind: "warning", message: "Execution outcome is unknown. This request has been preserved; it will not be resent." });
  if (state === "failed") onPart({ kind: "error", message: String(row.result?.error ?? row.result?.summary ?? "Request failed") });
  return state;
}
