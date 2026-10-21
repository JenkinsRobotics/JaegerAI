/* Wire types for the Jaeger gateway (core/gateway/server.py). Only the fields
 * this UI reads are typed; everything else passes through untouched. */

/** PROPOSED (Gateway bot, 2026-10-18): specialists carry a working role. */
export type AgentRole = "lead" | "specialist" | "native" | "reverse-engineer" | "builder" | "reviewer" | "researcher" | "designer" | string;

/** PROPOSED (Gateway bot): one skill an agent has. `source_path` is where it lives on disk (tooltip only). */
export interface AgentSkill {
  id: string;
  name: string;
  description?: string;
  source_path?: string;
}
/** Who actually runs the agent's work: Jaeger itself or a delegate CLI. */
export type Runner = "native" | `delegate:${string}` | string;

export interface Agent {
  /** Explicit server-supported menu actions; omitted/false means unavailable. */
  ui_actions?: Partial<import("./agentActions").AgentCaps>;
  id: string;
  name: string;
  display_name?: string;
  role?: AgentRole;
  kind?: string;
  deleted?: boolean;
  archived?: boolean;
  presentation?: { display_name?: string; archived?: boolean; pinned?: boolean; pin_order?: number };
  hidden?: boolean;
  disabled?: boolean;
  runner?: Runner;
  avatar_url?: string;
  icon_preset?: string | null;
  icon_choices?: string[];
  metadata?: Record<string, unknown>;
  /** PROPOSED: the agent's skills (GET /v1/agents and the specialist/role responses). */
  skills?: AgentSkill[];
  /** PROPOSED (agent-menu spec sent to the Gateway bot): optional; absent on today's gateway. */
  pinned?: boolean;
  pin_order?: number | null;
  section_id?: string | null;
  unread_count?: number;
  last_read_message_id?: string | null;
  primary?: boolean;
  last_message?: { id: string; created_at: string | number; kind?: string; preview?: string; author?: string } | null;
  /** Tool allow-list; unchanged on the wire. */
  allowed_tools?: string[];
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
  | { type: "tool"; call_id?: string | null; tool?: string; status?: string; state?: string; input?: unknown; output?: unknown }
  /** 417d8a0c: an approval the turn asked for. call_id is usually null, so it matches its tool on tool+target. */
  | { type: "approval"; approval_id: string; call_id?: string | null; tool?: string; target?: string; status?: string; state?: string; decision?: string | null }
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
  provenance?: { authorized?: boolean; session_id?: string; request_id?: string };
  result?: unknown;
  error?: string | null;
  run_history?: unknown[];
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
  thread_handoff_id?: string;
  reply_to_handoff_id?: string | null;
  from_agent_id?: string;
  request_id?: string | null;
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
