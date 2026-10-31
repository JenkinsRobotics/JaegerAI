/* One seam between the Agents-tab orchestration UI and its data.
 * EXISTING endpoints are used for real (agents, summary, handoffs, tasks,
 * handoff exchange, /v1/events/stream). The six GAPs sit behind GapProvider so
 * the Gateway bot's endpoints can drop in without touching components:
 *   G1 activity history   GET /v1/activity?since=&limit=     → gaps.activity
 *   G2 handoff check      handoff.check + agent.handoff.checked (read in feed.ts)
 *   G3 typed artifacts    handoff.result.artifact_refs       (read in feed.ts)
 *   G4 agent runner       agent.runner                        → gaps.runner
 *   G5 handoff↔task link  handoff.task_id                     (read in feed.ts)
 *   G6 agent status event agent.status.changed                (read in feed.ts) */
import type { JaegerSource } from "../api/source";
import type { Agent, GatewayEvent, HandoffExchange, Task } from "../api/types";
import { visible } from "../agents/agentsLogic";
import { activityItemRow, LEAD_ID } from "./feed";
import type { ActivityPage, ActivityRow, AgentLive, OrchestrationSnapshot } from "./types";

export interface GapProvider {
  kind: "derived" | "mock" | "gateway";
  /** G1: server-side history, newest first; `before` = previous page's
   * `next_before`. Undefined → backfill from the snapshot only. */
  activity?(q: { before?: number; agentId?: string; names: (id: string) => string }): Promise<{ rows: ActivityRow[]; nextBefore?: number }>;
  /** G4: agent-level runner. */
  runner(agent: Agent, tasks: Task[]): string | undefined;
}

export interface OrchestrationAdapter {
  snapshot(): Promise<OrchestrationSnapshot>;
  /** Global event stream; undefined → the hook polls. */
  follow?(onEvent: (e: GatewayEvent) => void, signal: AbortSignal): Promise<void>;
  exchange(handoffId: string): Promise<HandoffExchange>;
  gaps: GapProvider;
}

const ACTIVE = new Set(["queued", "running", "needs_owner", "paused"]);

/** Pre-G4: an agent's runner is its active task's runner, if any. */
export const derivedGaps: GapProvider = {
  kind: "derived",
  runner(agent, tasks) {
    const own = (agent as Agent & { runner?: string }).runner;
    if (own) return own;
    const task = tasks.find((t) => (t.agent_id ?? t.owning_agent) === agent.id && ACTIVE.has(String(t.state)));
    return task?.runner ?? undefined;
  },
};

/** G1 page → rows. Shared by the gateway and mock providers. */
export function pageRows(page: ActivityPage, names: (id: string) => string) {
  return { rows: page.items.flatMap((i) => activityItemRow(i, names) ?? []), nextBefore: page.has_more && page.next_before != null ? page.next_before : undefined };
}

/** G1 against `GET /v1/activity` (same origin, caller auth via the proxy). */
/** Bases whose gateway answered 404/405/501 on /v1/activity this page session. */
const NO_ACTIVITY = new Set<string>();
export const resetActivityProbe = () => NO_ACTIVITY.clear();

export function gatewayActivity(base = "", fetchImpl: typeof fetch = (...a) => fetch(...a)): NonNullable<GapProvider["activity"]> {
  return async ({ before, agentId, names }) => {
    if (NO_ACTIVITY.has(base)) return { rows: [] };
    const qs = new URLSearchParams({ limit: "50" });
    if (before != null) qs.set("before", String(before));
    if (agentId) qs.set("agent_id", agentId); // matches agent_id or actor_id (caller)
    const res = await fetchImpl(`${base}/v1/activity?${qs}`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    // Older gateways: no G1 route → history comes from the snapshot backfill only.
    if (res.status === 404 || res.status === 405 || res.status === 501) { NO_ACTIVITY.add(base); return { rows: [] }; }
    if (!res.ok) throw new Error(`activity ${res.status}`);
    return pageRows((await res.json()) as ActivityPage, names);
  };
}

/** Use once the gateway ships G1–G6; until then `derivedGaps`. */
export const gatewayGaps: GapProvider = { ...derivedGaps, kind: "gateway", activity: gatewayActivity() };

export function liveAdapter(source: JaegerSource, gaps: GapProvider = derivedGaps): OrchestrationAdapter {
  return {
    gaps,
    async snapshot() {
      const [agents, summaries, handoffs, tasks] = await Promise.all([source.agents(), source.agentsSummary(), source.handoffs(), source.tasks()]);
      return { agents, summaries, handoffs, tasks };
    },
    follow: source.globalEvents ? (onEvent, signal) => source.globalEvents!(onEvent, signal) : undefined,
    exchange: (id) => source.handoffExchange(id),
  };
}

/** Lead first, then specialists with live work, then the rest by name. */
export function agentsLive(s: OrchestrationSnapshot, gaps: GapProvider, statusOverrides: Record<string, string> = {}): AgentLive[] {
  const byId = new Map(s.summaries.map((x) => [x.id, x]));
  // The shared visible() rule is for the roster (hides hidden/archived, runtime
  // roles, third-party and internal agents). Here an agent also belongs on the
  // team if it took part in a handoff or owns a task, even when hidden.
  const worked = new Set<string>();
  for (const h of s.handoffs) { if (h.to_agent_id) worked.add(h.to_agent_id); if (h.from_agent_id) worked.add(h.from_agent_id); }
  for (const t of s.tasks) { const id = t.agent_id ?? t.owning_agent; if (id) worked.add(id); }
  const rows = s.agents.filter((a) => !a.deleted && (visible(a) || worked.has(a.id))).map((agent): AgentLive => {
    const summary = byId.get(agent.id);
    const task = summary?.task ?? s.tasks.find((t) => (t.agent_id ?? t.owning_agent) === agent.id && ACTIVE.has(String(t.state)));
    return {
      agent, summary,
      status: statusOverrides[agent.id] ?? summary?.status ?? (task && ACTIVE.has(String(task.state)) ? "working" : "idle"),
      runner: gaps.runner(agent, s.tasks),
      currentTask: task ? { task_id: task.task_id, goal: task.goal, eta: task.eta, state: task.state } : undefined,
      offRoster: !visible(agent) || undefined,
    };
  });
  const rank = (r: AgentLive) => (r.agent.id === LEAD_ID || r.agent.role === "lead" ? 0 : r.status === "idle" ? 2 : 1);
  return rows.sort((a, b) => rank(a) - rank(b) || (a.agent.display_name ?? a.agent.name).localeCompare(b.agent.display_name ?? b.agent.name));
}
