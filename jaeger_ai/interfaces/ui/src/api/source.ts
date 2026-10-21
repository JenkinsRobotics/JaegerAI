import type { HomeOptions, HomeSessions } from "../chat/homeSession";
import type { ChatSession } from "../chat/host";
import type { Agent, AgentSummary, GatewayEvent, Handoff, HandoffExchange, SessionDetail, SessionRow, Task } from "./types";

/** Everything the screen needs from Jaeger. The live adapter calls the
 * gateway through same-origin paths; the mock adapter replays sample data. */
/** 201 from the bytes upload route. */
export interface UploadedAttachment { attachment_id: string; name: string; mime: string; size: number; sha256: string }

import type { AgentActions } from "./agentActions";

export interface PendingApproval {
  approval_id: string; session_id?: string; kind: string; prompt: string;
  task?: string; status: string;
}

export interface RequestSnapshot {
  request_id: string; session_id: string; turn_id?: string; status: string; input_text?: string;
  result?: { output?: string; error?: string; summary?: string; [key: string]: unknown };
}
export interface ConnectedApp {
  id: string; name: string; description?: string; category?: string; status: string; actions: string[];
  state: { value: string; detail?: string; version?: string; checked_at?: number };
}
export interface ConnectAppsListing { apps: ConnectedApp[]; categories: { id: string; label: string }[]; connected_count: number }
export interface ModelInventory {
  active?: { provider: string; model: string };
  providers: { id: string; display_name: string; reachable: boolean; configured: boolean; reason?: string; models: { id: string; available?: boolean; usable_for_react?: boolean }[] }[];
}
export interface ModelSettings {
  inventory(): Promise<ModelInventory>;
  read(sessionId: string): Promise<{ session_id: string; model?: string | null; provider?: string | null }>;
  save(sessionId: string, model: string | null): Promise<void>;
}
export interface ScheduleJob { id: string; name: string; prompt: string; cron: string; enabled: boolean; state: string; next_fire_at?: string }
export type ScheduleAction = "create" | "update" | "pause" | "resume" | "delete" | "restore" | "run";
export interface ControlResult { ok: boolean; operation_id: string; result?: unknown; error?: string; http_status?: number }
export interface ScheduleControls {
  list(): Promise<{ jobs: ScheduleJob[]; scheduler: string }>;
  history(name: string): Promise<{ tasks: Task[]; requests: RequestSnapshot[] }>;
  mutate(action: ScheduleAction, body: { operation_id: string; job_id?: string; name?: string; prompt?: string; schedule?: string }): Promise<ControlResult>;
  operation(id: string): Promise<{ receipt: ControlResult | null }>;
}
export interface LibraryDocument { id: string; title: string; content: string; digest: string; revision?: number; archived?: boolean; editable?: boolean }
export interface LibraryControls {
  list(): Promise<{ documents: Omit<LibraryDocument, "content">[]; collections: { id: string; label: string; kind: string }[] }>;
  search(query: string): Promise<{ results: { id: string; title: string; snippet: string }[] }>;
  read(id: string): Promise<LibraryDocument>;
  versions(id: string): Promise<{ versions: { revision: number; title: string; created_at: number }[] }>;
  mutate(action: "create" | "save" | "archive" | "restore" | "version", id: string, body: Record<string, unknown>): Promise<ControlResult & { document?: { id: string; revision: number; digest: string; archived: boolean } }>;
  operation(id: string): Promise<{ receipt: (ControlResult & { document?: { id: string } }) | null }>;
}

export interface JaegerSource {
  library?: LibraryControls;
  skills?(query?: string): Promise<{ skills: { name: string; category: string; description: string; lifecycle: string }[]; count: number }>;
  schedules?: ScheduleControls;
  modelSettings?: ModelSettings;
  connectApps?: {
    list(): Promise<ConnectAppsListing>;
    state(id: string): Promise<{ id: string; state: ConnectedApp["state"] }>;
    install(id: string): Promise<{ id?: string; state?: ConnectedApp["state"] }>;
  };
  /** Read-only same-ID acceptance and terminal-outcome lookup. */
  requestStatus?(sessionId: string, requestId: string): Promise<RequestSnapshot>;
  sessionControl?(sessionId: string): Promise<{ latest_request?: { request_id: string; status: string } | null }>;
  readonly kind: "live" | "mock";
  agents(): Promise<Agent[]>;
  agentsSummary(): Promise<AgentSummary[]>;
  sessions(query?: { agent_id?: string }): Promise<SessionRow[]>;
  session(id: string): Promise<SessionDetail>;
  createSession(body: { agent_id?: string; title?: string }): Promise<SessionRow>;
  /** PATCH /v1/sessions/{id}: rename or archive a chat. */
  updateSession(id: string, body: { title?: string; archived?: boolean }): Promise<void>;
  /** POST /v1/agents: a new specialist the lead can hand work to. */
  /** Agent context-menu actions (agentActions.ts); optional, gated by agentCaps. */
  agentActions?: AgentActions;
  createAgent(body: { name: string; display_name?: string; role?: string; metadata?: Record<string, unknown> }): Promise<Agent>;
  /** The specialist's side of one hand-off: its worker session and messages. */
  replyHandoff?(handoffId: string, task: string, requestId: string): Promise<Handoff>;
  handoffExchange(handoffId: string): Promise<HandoffExchange>;
  /** POST /v1/sessions/{id}/turns. `start_event_id` is the durable cursor of
   * this turn's turn.start (stream from start_event_id - 1). */
  send(sessionId: string, text: string, requestId: string, attachmentIds?: string[]): Promise<TurnReceipt>;
  /** POST /v1/sessions/{id}/attachments: register a workspace file (the gateway sizes and hashes it). */
  addAttachment(sessionId: string, body: { path: string; filename?: string; mime_type?: string }): Promise<{ attachment_id: string }>;
  /** PROVISIONAL (bytes upload, gateway-side staging): the same endpoint with the file's bytes instead
   * of a path. Only called when the bytes-upload flag is on (composer.bytesUploadEnabled). */
  /** POST /v1/sessions/{id}/attachments/upload (bytes, 25 MB max): 201 → the stored file. 404/405 = not
   * supported by this gateway; 413 = too large. */
  uploadAttachment?(sessionId: string, body: { name: string; mime: string; data_base64: string }, idempotencyKey?: string): Promise<UploadedAttachment>;
  cancel(sessionId: string, requestId?: string): Promise<void>;
  pendingApprovals?(sessionId: string): Promise<PendingApproval[]>;
  approve(sessionId: string, approvalId: string, approved: boolean): Promise<void>;
  tasks(): Promise<Task[]>;
  agentHome?(agentId: string): Promise<{ session_id: string; agent_id: string }>;
  taskActions?: {
    create(body: { session_id: string; goal: string; request_id: string; proposal: true }): Promise<{ task_id: string; status: string; replayed: boolean }>;
    edit(id: string, goal: string, expected_updated_at: number): Promise<Task>;
    approve(id: string, expected_updated_at: number): Promise<void>;
    cancel(id: string): Promise<void>;
  };
  handoffs(query?: { session_id?: string }): Promise<Handoff[]>;
  /** Its own home-chat implementation, when the source has one (dev mock only). */
  homeSessions?(opts: HomeOptions): HomeSessions;
  /** Rich transcript, when the source has one (dev mock only). */
  transcript?(sessionId: string): ChatSession | undefined;
  /** Session SSE (`/v1/sessions/{id}/stream?last_event_id=<cursor>`). Resolves
   * when the stream ends or `signal` aborts; throws GatewayError on HTTP errors. */
  /** PROPOSED global event stream (agent.updated/created/deleted, section.updated/deleted, agent.unread); the
   * channel is not in the spec yet (GET /v1/events assumed). Optional: without it the roster polls. */
  globalEvents?(onEvent: (event: GatewayEvent) => void, signal: AbortSignal): Promise<void>;
  stream(sessionId: string, cursor: number | undefined, onEvent: (event: GatewayEvent) => void, signal: AbortSignal): Promise<void>;
}

export interface TurnReceipt {
  request_id: string;
  turn_id?: string;
  start_event_id?: number;
  status?: string;
  replayed?: boolean;
}
