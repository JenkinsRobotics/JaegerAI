import { requestOutcome } from "./requestOutcome";
/* Follow exactly one turn on the session stream (review #3).
 *
 * Mirrors core/gateway/openai_compat.py (_follow): send first, then stream
 * from `start_event_id - 1`, keep only this request's events, and stop on its
 * own terminal event. On top of that:
 *   - the cursor never moves backwards (`max(start-1, last seen)`) and any
 *     frame with id <= cursor is dropped, so a replay cannot settle the turn;
 *   - when the stream drops or ends early, reconnect with backoff and resume
 *     from the cursor (`?last_event_id=`, per server.py _sse_stream);
 *   - a 410 (cursor no longer retained) reconciles the original request;
 *     unavailable lookup leaves its outcome unknown without replay. */
import { GatewayError } from "../api/gateway";
import type { JaegerSource } from "../api/source";
import type { GatewayEvent } from "../api/types";
import { mapEvent } from "./eventMap";
import type { ChatPart, TurnState } from "./host";

export const DEFAULT_BACKOFF_MS = [250, 500, 1000, 2000, 4000, 8000];

export interface FollowOptions {
  source: Pick<JaegerSource, "stream" | "requestStatus">;
  sessionId: string;
  requestId: string;
  turnId?: string;
  /** Cursor to resume after (start_event_id - 1, or the last seen id). */
  cursor: number;
  signal: AbortSignal;
  onPart: (part: ChatPart) => void;
  /** Every accepted frame's id, so the caller can keep a per-session cursor. */
  onCursor?: (eventId: number) => void;
  agentName?: (id: string) => string;
  backoffMs?: number[];
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
}

const defaultSleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });

function eventTurnId(event: GatewayEvent): string | undefined {
  const fromPayload = event.payload && typeof event.payload === "object" ? (event.payload as Record<string, unknown>).turn_id : undefined;
  const value = event.turn_id ?? fromPayload;
  return typeof value === "string" ? value : undefined;
}

/** True when this frame belongs to the followed turn. */
export function belongsToTurn(event: GatewayEvent, requestId: string, turnId?: string): boolean {
  if (event.request_id !== requestId) return false;
  const tid = eventTurnId(event);
  return !(turnId && tid && tid !== turnId);
}

export async function followTurn(opts: FollowOptions): Promise<{ state: TurnState }> {
  const backoff = opts.backoffMs ?? DEFAULT_BACKOFF_MS;
  const sleep = opts.sleep ?? defaultSleep;
  let cursor = opts.cursor;
  let attempt = 0;
  let answer = "";
  let generation = 0;
  const reconcile = async (): Promise<{ state: TurnState }> => {
    try {
      const row = await opts.source.requestStatus?.(opts.sessionId, opts.requestId);
      if (row?.request_id === opts.requestId && row.session_id === opts.sessionId) {
        const state = requestOutcome(row, opts.onPart, answer);
        if (state) return { state };
      }
    } catch { /* unavailable lookup cannot settle execution */ }
    opts.onPart({ kind: "warning", message: "Connection lost. Request outcome is unknown; no work was resent. Check this request again after reconnecting." });
    return { state: "unknown" };
  };

  while (!opts.signal.aborted) {
    const ownerGeneration = ++generation;
    const local = new AbortController();
    const stop = () => local.abort();
    opts.signal.addEventListener("abort", stop, { once: true });
    let terminal: TurnState | undefined;
    let progressed = false;
    try {
      await opts.source.stream(opts.sessionId, cursor, (event) => {
        if (terminal || ownerGeneration !== generation || local.signal.aborted) return;
        const id = typeof event.event_id === "number" && Number.isFinite(event.event_id) ? event.event_id : undefined;
        if (id !== undefined) {
          if (id <= cursor) return; // replayed or duplicate frame
          cursor = id;
          progressed = true;
          opts.onCursor?.(id);
        }
        if (!belongsToTurn(event, opts.requestId, opts.turnId)) return;
        const mapped = mapEvent(event, opts.agentName);
        mapped?.parts.forEach((part) => {
          if (part.kind === "markdownContent") answer += part.text;
          opts.onPart(part);
        });
        // Text-only execution may emit no text deltas; its durable terminal
        // receipt is the answer. Append only a missing suffix, never duplicate
        // a streamed answer on finish/reconnect.
        if (event.event === "turn.finish" || event.event === "turn.reconciled") {
          const output = event.payload?.output;
          if (typeof output === "string" && output.startsWith(answer) && output.length > answer.length) {
            opts.onPart({ kind: "markdownContent", text: output.slice(answer.length) });
            answer = output;
          }
        }
        if (mapped?.state) { terminal = mapped.state; local.abort(); }
      }, local.signal);
    } catch (error) {
      if (terminal) return { state: terminal };
      if (opts.signal.aborted) break;
      if (error instanceof GatewayError && error.status === 410) {
        opts.onPart({ kind: "error", message: "The stream cursor expired before this turn finished. Reload the session to see the result." });
        return reconcile();
      }
      if (error instanceof GatewayError && error.status >= 400 && error.status < 500) {
        opts.onPart({ kind: "error", message: error.message });
        return reconcile();
      }
    } finally {
      if (generation === ownerGeneration) generation++;
      opts.signal.removeEventListener("abort", stop);
    }
    if (terminal) return { state: terminal };
    if (opts.signal.aborted) break;
    // Stream dropped or ended before our terminal event: back off, then resume.
    if (progressed) attempt = 0;
    if (attempt >= backoff.length) {
      opts.onPart({ kind: "error", message: "Lost the connection to the gateway." });
      return reconcile();
    }
    await sleep(backoff[attempt++], opts.signal);
  }
  return reconcile();
}
