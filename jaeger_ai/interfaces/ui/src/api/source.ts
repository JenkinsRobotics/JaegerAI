import type { HomeOptions, HomeSessions } from "../chat/homeSession";
import type { ChatSession } from "../chat/host";
import type { Agent, AgentSummary, GatewayEvent, Handoff, HandoffExchange, SessionDetail, SessionRow, Task } from "./types";

/** Everything the screen needs from Jaeger. The live adapter calls the
 * gateway through same-origin paths; the mock adapter replays sample data. */
export interface JaegerSource {
  readonly kind: "live" | "mock";
  agents(): Promise<Agent[]>;
  agentsSummary(): Promise<AgentSummary[]>;
  sessions(query?: { agent_id?: string }): Promise<SessionRow[]>;
  session(id: string): Promise<SessionDetail>;
  createSession(body: { agent_id?: string; title?: string }): Promise<SessionRow>;
  /** PATCH /v1/sessions/{id}: rename or archive a chat. */
  updateSession(id: string, body: { title?: string; archived?: boolean }): Promise<void>;
  /** POST /v1/agents: a new specialist the lead can hand work to. */
  createAgent(body: { name: string; display_name?: string; role?: string; metadata?: Record<string, unknown> }): Promise<Agent>;
  /** The specialist's side of one hand-off: its worker session and messages. */
  handoffExchange(handoffId: string): Promise<HandoffExchange>;
  /** POST /v1/sessions/{id}/turns. `start_event_id` is the durable cursor of
   * this turn's turn.start (stream from start_event_id - 1). */
  send(sessionId: string, text: string, requestId: string, attachmentIds?: string[]): Promise<TurnReceipt>;
  /** POST /v1/sessions/{id}/attachments: register a workspace file (the gateway sizes and hashes it). */
  addAttachment(sessionId: string, body: { path: string; filename?: string; mime_type?: string }): Promise<{ attachment_id: string }>;
  /** PROVISIONAL (bytes upload, gateway-side staging): the same endpoint with the file's bytes instead
   * of a path. Only called when the bytes-upload flag is on (composer.bytesUploadEnabled). */
  uploadAttachment?(sessionId: string, body: { filename: string; mime_type: string; data_base64: string }): Promise<{ attachment_id: string }>;
  cancel(sessionId: string, requestId?: string): Promise<void>;
  approve(sessionId: string, approvalId: string, approved: boolean): Promise<void>;
  tasks(): Promise<Task[]>;
  handoffs(query?: { session_id?: string }): Promise<Handoff[]>;
  /** Its own home-chat implementation, when the source has one (dev mock only). */
  homeSessions?(opts: HomeOptions): HomeSessions;
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
