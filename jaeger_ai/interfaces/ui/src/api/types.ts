/* Wire types for the Jaeger gateway (core/gateway/server.py). Only the fields
 * this UI reads are typed; everything else passes through untouched. */

export type AgentRole = "lead" | "specialist" | "native" | string;
/** Who actually runs the agent's work: Jaeger itself or a delegate CLI. */
export type Runner = "native" | `delegate:${string}` | string;

export interface Agent {
  id: string;
  name: string;
  display_name?: string;
  role?: AgentRole;
  kind?: string;
  hidden?: boolean;
  disabled?: boolean;
  runner?: Runner;
  avatar_url?: string;
  metadata?: Record<string, unknown>;
}

export type AgentStatus = "idle" | "working" | "waiting_approval" | "blocked" | "error" | string;

/** One row of GET /v1/agents/summary. */
export interface AgentSummary {
  id: string;
  display_name?: string;
  role?: AgentRole;
  status?: AgentStatus;
  last_activity_at?: number | null;
  last_preview?: string;
  last_source?: "handoff" | "task" | "chat" | null;
  last_handoff_id?: string | null;
  session_id?: string | null;
  seen_at?: number | null;
  unseen?: boolean;
  task?: Pick<Task, "task_id" | "goal" | "state" | "eta" | "runner" | "updated_at"> | null;
}

export interface SessionRow {
  session_id: string;
  title?: string;
  agent_id?: string | null;
  created_at?: number;
  updated_at?: number;
  last_message_preview?: string;
  last_activity_at?: number;
  last_event_id?: number;
  message_count?: number;
  archived?: boolean;
}

/** One persisted response part (core/gateway/turn_parts.py). */
export type PersistedPart =
  | { type: "text"; text: string }
  | { type: "reasoning"; text: string; duration_ms?: number }
  | { type: "tool"; call_id?: string; tool?: string; status?: "running" | "done" | "error"; input?: unknown; output?: unknown }
  | { type: "plan"; [key: string]: unknown }
  | { type: "handoff"; direction: "to" | "from"; handoff_id?: string; agent_id?: string; agent_name?: string; status?: string };

export interface SessionMessage {
  role: "user" | "assistant" | "system" | "tool" | string;
  content?: string;
  created_at?: number;
  /** Epoch seconds; the store serialises it as a string. */
  timestamp?: number | string;
  request_id?: string;
  parts?: PersistedPart[];
}

export interface SessionDetail extends SessionRow {
  messages?: SessionMessage[];
}

export type TaskState = "queued" | "running" | "needs_owner" | "paused" | "blocked" | "failed" | "done" | "cancelled" | string;

export interface Task {
  task_id: string;
  goal?: string;
  state?: TaskState;
  agent_id?: string | null;
  owning_agent?: string | null;
  eta?: number | string | null;
  runner?: Runner | null;
  updated_at?: number;
  created_at?: number;
}

export interface Handoff {
  id: string;
  from_agent_id?: string;
  to_agent_id?: string;
  session_id?: string | null;
  parent_run_id?: string | null;
  status?: string;
  task?: string;
  result?: { summary?: string } | null;
  updated_at?: number;
  created_at?: number;
}

/** GET /v1/handoffs/{id}/messages (proxied as /api/handoffs/{id}/messages). */
export interface HandoffExchange {
  handoff_id: string;
  session_id?: string | null;
  to_agent_id: string;
  status?: string;
  task?: string;
  worker_session_id: string;
  summary?: string;
}

/** One frame of the gateway SSE stream: `id:` / `event:` / `data:` lines. */
export interface GatewayEvent {
  event: string;
  event_id?: number;
  session_id?: string;
  request_id?: string;
  created_at?: number;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}
