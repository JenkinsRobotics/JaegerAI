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
  send(sessionId: string, text: string): Promise<{ request_id?: string }>;
  cancel(sessionId: string, requestId?: string): Promise<void>;
  approve(sessionId: string, approvalId: string, approved: boolean): Promise<void>;
  tasks(): Promise<Task[]>;
  handoffs(query?: { session_id?: string }): Promise<Handoff[]>;
  /** Session SSE (`/v1/sessions/{id}/stream`), resumable from a cursor. */
  stream(sessionId: string, cursor: number | undefined, onEvent: (event: GatewayEvent) => void, signal: AbortSignal): Promise<void>;
}
