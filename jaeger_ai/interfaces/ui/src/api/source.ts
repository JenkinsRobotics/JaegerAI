import type { ChatSession } from "../chat/host";
import type { Agent, AgentSummary, GatewayEvent, Handoff, SessionDetail, SessionRow, Task } from "./types";

/** Everything the screen needs from Jaeger. The live adapter calls the
 * gateway through same-origin paths; the mock adapter replays sample data. */
export interface JaegerSource {
  readonly kind: "live" | "mock";
  agents(): Promise<Agent[]>;
  agentsSummary(): Promise<AgentSummary[]>;
  sessions(query?: { agent_id?: string }): Promise<SessionRow[]>;
  session(id: string): Promise<SessionDetail>;
  createSession(body: { agent_id?: string; title?: string }): Promise<SessionRow>;
  /** POST /v1/sessions/{id}/turns. `start_event_id` is the durable cursor of
   * this turn's turn.start (stream from start_event_id - 1). */
  send(sessionId: string, text: string, requestId: string): Promise<TurnReceipt>;
  cancel(sessionId: string, requestId?: string): Promise<void>;
  approve(sessionId: string, approvalId: string, approved: boolean): Promise<void>;
  tasks(): Promise<Task[]>;
  handoffs(query?: { session_id?: string }): Promise<Handoff[]>;
  /** Rich transcript, when the source has one (dev mock only). */
  transcript?(sessionId: string): ChatSession | undefined;
  /** Session SSE (`/v1/sessions/{id}/stream?last_event_id=<cursor>`). Resolves
   * when the stream ends or `signal` aborts; throws GatewayError on HTTP errors. */
  stream(sessionId: string, cursor: number | undefined, onEvent: (event: GatewayEvent) => void, signal: AbortSignal): Promise<void>;
}

export interface TurnReceipt {
  request_id: string;
  turn_id?: string;
  start_event_id?: number;
  status?: string;
  replayed?: boolean;
}
