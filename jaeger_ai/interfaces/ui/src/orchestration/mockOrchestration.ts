/* dev mock data for the orchestration harness and tests. Never imported by
 * the app entry; the check-no-mock marker above guards production bundles.
 * Fills every GAP (G1–G6) with typed sample data in the shapes the plan
 * asks the Gateway bot for. */
import type { Agent, AgentSummary, GatewayEvent, Handoff, HandoffExchange, Task } from "../api/types";
import type { GapProvider, OrchestrationAdapter } from "./adapter";
import { derivedGaps } from "./adapter";

const now = () => Math.floor(Date.now() / 1000);
export function mockSnapshotData(t0 = now()) {
  const agents: Agent[] = [
    { id: "native:jaeger", name: "jaeger", display_name: "Jaeger", role: "lead" },
    { id: "native:mac", name: "mac", display_name: "Mac App", role: "builder" },
    { id: "native:reviewer", name: "reviewer", display_name: "Reviewer", role: "reviewer" },
    { id: "native:research", name: "research", display_name: "Research", role: "researcher" },
    { id: "native:design", name: "design", display_name: "Design", role: "designer" },
  ];
  const tasks: Task[] = [
    { task_id: "t-build", goal: "Fix the notarize step", state: "running", agent_id: "native:mac", runner: "delegate:codex", eta: "12m", updated_at: t0 - 120, provenance: { request_id: "r-build" } },
    { task_id: "t-review", goal: "Review PR #412", state: "completed_verified", agent_id: "native:reviewer", runner: "native", updated_at: t0 - 900, provenance: { request_id: "r-review" } },
    { task_id: "t-icons", goal: "Export app icons", state: "needs_owner", agent_id: "native:design", runner: "native", updated_at: t0 - 1500 },
  ];
  const handoffs: Handoff[] = [
    { id: "h-build", from_agent_id: "native:jaeger", to_agent_id: "native:mac", task: "Fix the notarize step", status: "running", request_id: "r-build", created_at: t0 - 300, updated_at: t0 - 120 },
    { id: "h-review", from_agent_id: "native:jaeger", to_agent_id: "native:reviewer", task: "Review PR #412", status: "completed", request_id: "r-review", created_at: t0 - 2400, updated_at: t0 - 900,
      result: { summary: "2 nits, approved", artifact_refs: [{ kind: "commit", ref: "9f3c2ab17e" }] } as Handoff["result"],
      ...{ check: { state: "passed", evidence_ref: "https://github.com/example/jaeger/pull/412", checked_by: "native:jaeger", checked_at: t0 - 880 } } },
    { id: "h-research", from_agent_id: "native:jaeger", to_agent_id: "native:research", task: "Compare PWA install flows", status: "failed", created_at: t0 - 4000, updated_at: t0 - 3500, result: { summary: "source site blocked" } },
  ];
  const summaries: AgentSummary[] = [
    { id: "native:mac", status: "working" as AgentSummary["status"], task: tasks[0] },
    { id: "native:design", status: "waiting" as AgentSummary["status"], task: tasks[2], unseen: true },
  ];
  return { agents, summaries, handoffs, tasks };
}

export const mockGaps: GapProvider = {
  kind: "mock",
  runner: (agent, tasks) => ({ "native:research": "delegate:hermes" } as Record<string, string>)[agent.id] ?? derivedGaps.runner(agent, tasks),
  activity: async () => [],
};

/** Scripted global-stream frames, emitted one per `stepMs` (0 = all at once). */
export function mockFrames(t0 = now()): GatewayEvent[] {
  return [
    { event: "agent.status.changed", event_id: 1001, created_at: t0 - 60, payload: { agent_id: "native:reviewer", status: "checking" } },
    { event: "agent.handoff.checked", event_id: 1002, created_at: t0 - 30, payload: { handoff_id: "h-build", state: "pending", checked_by: "native:reviewer" } },
    { event: "approval.request", event_id: 1003, created_at: t0 - 10, session_id: "s-home", payload: { approval_id: "a-1", agent_id: "native:mac", title: "Run notarytool" } },
  ];
}

export function mockAdapter(opts: { stepMs?: number; fail?: boolean } = {}): OrchestrationAdapter {
  const data = mockSnapshotData();
  return {
    gaps: mockGaps,
    snapshot: async () => { if (opts.fail) throw new Error("Gateway unreachable"); return data; },
    follow: async (onEvent, signal) => {
      for (const f of mockFrames()) {
        if (signal.aborted) return;
        if (opts.stepMs) await new Promise((r) => setTimeout(r, opts.stepMs));
        onEvent(f);
      }
      await new Promise<void>((r) => signal.addEventListener("abort", () => r(), { once: true }));
    },
    exchange: async (id): Promise<HandoffExchange> => {
      const h = data.handoffs.find((x) => x.id === id);
      return { handoff_id: id, to_agent_id: h?.to_agent_id ?? "", from_agent_id: h?.from_agent_id, task: h?.task, status: h?.status, worker_session_id: `ws-${id}`, summary: h?.result?.summary };
    },
  };
}
