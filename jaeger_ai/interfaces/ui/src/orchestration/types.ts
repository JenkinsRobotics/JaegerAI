/* Agents-tab orchestration model (plan 2026-10-31). Fields marked GAP come
 * from the Gateway bot's pending work (G1–G6). Until it ships they're filled
 * by the GapProvider in adapter.ts: derived from EXISTING data in live mode,
 * typed mocks in the dev harness. */
import type { Agent, AgentSummary, Handoff, Task } from "../api/types";

/** GAP G2 (handoff check). Before G2 the live adapter derives it from the linked
 * task's state; with no task, the check is "unchecked" (never "passed"). */
export type CheckState = "unchecked" | "pending" | "passed" | "failed";

export interface HandoffCheck {
  state: CheckState;
  /** Where the proof lives (test run, receipt, approver). */
  evidence?: OutputLink;
  checkedBy?: string;
  checkedAt?: number;
  note?: string;
  /** "derived" = computed in the UI from task/approval state; "gateway" = G2 record. */
  source: "derived" | "gateway";
}

/** GAP G3 (typed artifacts). */
export type OutputKind = "session" | "handoff" | "task" | "file" | "commit" | "url" | "approval";

export interface OutputLink {
  kind: OutputKind;
  label: string;
  /** In-app route (`/work/tasks?task=…`), `handoff:<id>` (opens the exchange
   * in the inspector), or an external https URL. */
  href: string;
  sha?: string;
  /** Not openable here (file path, commit SHA, http link): render as a copy chip of `href`. */
  copy?: boolean;
  /** G3 `verified` (gateway confirmed it exists). */
  verified?: boolean;
}

/** G1 `GET /v1/activity` item (gateway proposal 2026-10-31). */
export interface ActivityItem {
  event_id: number;
  kind: string;
  ts: number;
  agent_id: string;
  actor_id?: string | null;
  session_id?: string | null;
  summary?: string;
  needs_me?: boolean;
  refs?: { handoff_id?: string | null; task_id?: string | null; approval_id?: string | null; session_id?: string | null };
  data?: Record<string, unknown>;
}
export interface ActivityPage { items: ActivityItem[]; has_more: boolean; next_before?: number | null }

/** G2 check record on handoffs. */
export interface CheckRecord { state: CheckState; evidence_ref?: string | null; checked_by?: string | null; checked_at?: number | null; note?: string | null }
/** G3 artifact ref on handoff.result.artifact_refs. */
export interface ArtifactRef { kind: "file" | "commit" | "session" | "task" | "url"; ref: string; sha?: string | null; title?: string; verified?: boolean; url?: string | null }

export type ActivityKind =
  | "handoff.started"
  | "handoff.finished"
  | "handoff.failed"
  | "handoff.checked"
  | "task.created"
  | "task.updated"
  | "approval.requested"
  | "approval.resolved"
  | "agent.status";

export interface ActivityRow {
  /** Stable key for dedupe: `<kind>:<resource id>[:<state>]`. */
  key: string;
  kind: ActivityKind;
  agentId: string;
  /** Human sentence after the agent name: "handed off to Mac App". */
  action: string;
  at: number;
  /** The thing this activity produced or points at. */
  output?: OutputLink;
  handoffId?: string;
  taskId?: string;
  check?: HandoffCheck;
  /** Rows that need the user (approvals, failed checks). */
  needsYou?: boolean;
}

/** Live view of one specialist for the status list. */
export interface AgentLive {
  agent: Agent;
  summary?: AgentSummary;
  status: string;
  /** GAP G4: agent-level runner; live falls back to the current task's runner. */
  runner?: string;
  currentTask?: Pick<Task, "task_id" | "goal" | "eta" | "state">;
  /** Hidden from the roster by the shared visible() rule, but did work here. */
  offRoster?: boolean;
}

export interface OrchestrationSnapshot {
  agents: Agent[];
  summaries: AgentSummary[];
  handoffs: Handoff[];
  tasks: Task[];
}
