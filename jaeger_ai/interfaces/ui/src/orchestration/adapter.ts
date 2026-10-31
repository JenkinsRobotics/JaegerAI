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
import { LEAD_ID } from "./feed";
import type { ActivityRow, AgentLive, OrchestrationSnapshot } from "./types";

export interface GapProvider {
  kind: "derived" | "mock" | "gateway";
  /** G1: server-side history. Undefined → backfill from the snapshot. */
  activity?(): Promise<ActivityRow[]>;
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
  const rows = s.agents.filter(visible).map((agent): AgentLive => {
    const summary = byId.get(agent.id);
    const task = summary?.task ?? s.tasks.find((t) => (t.agent_id ?? t.owning_agent) === agent.id && ACTIVE.has(String(t.state)));
    return {
      agent, summary,
      status: statusOverrides[agent.id] ?? summary?.status ?? (task && ACTIVE.has(String(task.state)) ? "working" : "idle"),
      runner: gaps.runner(agent, s.tasks),
      currentTask: task ? { task_id: task.task_id, goal: task.goal, eta: task.eta, state: task.state } : undefined,
    };
  });
  const rank = (r: AgentLive) => (r.agent.id === LEAD_ID || r.agent.role === "lead" ? 0 : r.status === "idle" ? 2 : 1);
  return rows.sort((a, b) => rank(a) - rank(b) || (a.agent.display_name ?? a.agent.name).localeCompare(b.agent.display_name ?? b.agent.name));
}
