/* dev mock data for the orchestration harness and tests. Never imported by
 * the app entry; the check-no-mock marker above guards production bundles.
 * Shapes follow the Gateway bot's G1–G6 proposal (2026-10-31):
 * /workspace/jaeger-agents-tab-api-shapes.md. */
import type { Agent, AgentSummary, GatewayEvent, Handoff, HandoffExchange, Task } from "../api/types";
import type { GapProvider, OrchestrationAdapter } from "./adapter";
import { derivedGaps, pageRows } from "./adapter";
import type { ActivityItem, ActivityPage, ArtifactRef, CheckRecord } from "./types";

type GwAgent = Agent & { runner: string };                                  // G4
type GwHandoff = Handoff & { task_id: string | null; check: CheckRecord;     // G5, G2
  result?: { summary?: string; worker_session_id?: string; artifact_refs?: ArtifactRef[] } | null };
type GwTask = Task & { handoff_id: string | null };                         // G5

const now = () => Math.floor(Date.now() / 1000);
export function mockSnapshotData(t0 = now()) {
  const agents: GwAgent[] = [
    { id: "native:jaeger", name: "jaeger", display_name: "Jaeger", role: "lead", runner: "native" },
    { id: "native:mac", name: "mac", display_name: "Mac App", role: "builder", runner: "delegate:codex" },
    { id: "native:reviewer", name: "reviewer", display_name: "Reviewer", role: "reviewer", runner: "native" },
    { id: "native:research", name: "research", display_name: "Research", role: "researcher", runner: "delegate:hermes" },
    { id: "native:design", name: "design", display_name: "Design", role: "designer", runner: "native" },
  ];
  const tasks: GwTask[] = [
    { task_id: "t-build", goal: "Fix the notarize step", state: "running", agent_id: "native:mac", runner: "delegate:codex", eta: "12m", updated_at: t0 - 120, handoff_id: "h-build" },
    { task_id: "t-review", goal: "Review PR #412", state: "completed_verified", agent_id: "native:reviewer", runner: "native", updated_at: t0 - 900, handoff_id: "h-review" },
    { task_id: "t-icons", goal: "Export app icons", state: "needs_owner", agent_id: "native:design", runner: "native", updated_at: t0 - 1500, handoff_id: null },
  ];
  const handoffs: GwHandoff[] = [
    { id: "h-build", from_agent_id: "native:jaeger", to_agent_id: "native:mac", task: "Fix the notarize step", status: "running", task_id: "t-build", created_at: t0 - 300, updated_at: t0 - 120,
      check: { state: "unchecked", evidence_ref: null, checked_by: null, checked_at: null } },
    { id: "h-review", from_agent_id: "native:jaeger", to_agent_id: "native:reviewer", task: "Review PR #412", status: "completed", task_id: "t-review", created_at: t0 - 2400, updated_at: t0 - 900,
      result: { summary: "2 nits, approved", worker_session_id: "native:reviewer:req-412", artifact_refs: [
        { kind: "session", ref: "native:reviewer:req-412", sha: null, title: "Review session", verified: true },
        { kind: "commit", ref: "9f3c2ab17e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b", sha: null, title: "9f3c2ab", verified: true, url: "https://github.com/example/jaeger/commit/9f3c2ab17e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b" },
        { kind: "file", ref: "docs/review-412.md", sha: "4be1c0ffee", title: "review-412.md", verified: true },
        { kind: "url", ref: "http://127.0.0.1:18790/reports/412", sha: null, title: "Local report", verified: false },
      ] },
      check: { state: "passed", evidence_ref: "url:https://github.com/example/jaeger/pull/412", checked_by: "owner:matthew", checked_at: t0 - 880, note: "tests green" } },
    { id: "h-research", from_agent_id: "native:jaeger", to_agent_id: "native:research", task: "Compare PWA install flows", status: "failed", task_id: null, created_at: t0 - 4000, updated_at: t0 - 3500,
      result: { summary: "source site blocked", worker_session_id: "native:research:req-9" },
      check: { state: "failed", evidence_ref: "handoff:h-research", checked_by: "gateway", checked_at: t0 - 3500 } },
  ];
  const summaries: AgentSummary[] = [
    { id: "native:mac", status: "working" as AgentSummary["status"], task: tasks[0] },
    { id: "native:design", status: "waiting_approval" as AgentSummary["status"], task: tasks[2], unseen: true },
  ];
  return { agents: agents as Agent[], summaries, handoffs: handoffs as Handoff[], tasks: tasks as Task[] };
}

/** Older G1 history, two pages of `GET /v1/activity`. */
export function mockActivity(t0 = now()): ActivityItem[] {
  return [
    { event_id: 900, kind: "agent.handoff.finished", ts: t0 - 86400, agent_id: "native:design", actor_id: "native:jaeger", session_id: "*", summary: "Design finished: Draft onboarding art", needs_me: false,
      refs: { handoff_id: "h-art", task_id: null, approval_id: null, session_id: "native:design:req-art" },
      data: { handoff: { id: "h-art", from_agent_id: "native:jaeger", to_agent_id: "native:design", task: "Draft onboarding art", status: "completed", created_at: t0 - 90000, check: { state: "pending" } } } },
    { event_id: 880, kind: "project.checked", ts: t0 - 90000, agent_id: "native:reviewer", summary: "project release-1.4 check passed", needs_me: false, refs: { task_id: null },
      data: { project_id: "release-1.4", result: { ok: true, status: "passed", checked_at: t0 - 90000, agent_id: "native:reviewer" } } },
    { event_id: 870, kind: "turn.finish", ts: t0 - 95000, agent_id: "native:jaeger", actor_id: "codex", session_id: "codex:bridge-t1", summary: "codex (mcp) goal g-17 completed", needs_me: false,
      refs: { session_id: "codex:bridge-t1" }, data: { caller: { caller_id: "codex", caller_kind: "mcp", session_id: "codex:bridge-t1", request_id: "rq-17", status: "completed", goal_id: "g-17", thread: "t1", agent_id: "native:jaeger" } } },
    { event_id: 860, kind: "turn.failed", ts: t0 - 96000, agent_id: "native:jaeger", actor_id: "partner-bot", session_id: "agent:partner-bot:x", summary: "partner-bot (a2a) goal g-9 failed", needs_me: false,
      refs: { session_id: "agent:partner-bot:x" }, data: { error: "quota exceeded", caller: { caller_id: "partner-bot", caller_kind: "a2a", session_id: "agent:partner-bot:x", request_id: "rq-9", status: "failed", goal_id: "g-9", agent_id: "native:jaeger" } } },
    { event_id: 850, kind: "task.created", ts: t0 - 172800, agent_id: "native:mac", summary: "Task created", needs_me: false, refs: { task_id: "t-old" },
      data: { task: { task_id: "t-old", goal: "Bump Sparkle", state: "queued", agent_id: "native:mac" } } },
  ];
}

export const mockGaps: GapProvider = {
  kind: "mock",
  runner: derivedGaps.runner,
  activity: async ({ before, agentId, names }) => {
    const all = mockActivity().filter((i) => !agentId || i.agent_id === agentId || i.actor_id === agentId);
    const items = all.filter((i) => before == null || i.event_id < before).slice(0, 4);
    const last = items.at(-1);
    const page: ActivityPage = { items, has_more: !!last && all.some((i) => i.event_id < last.event_id), next_before: last?.event_id ?? null };
    return pageRows(page, names);
  },
};

/** Scripted global-stream frames in the proposed envelopes. */
export function mockFrames(t0 = now()): GatewayEvent[] {
  const data = mockSnapshotData(t0);
  const build = data.handoffs[0];
  return [
    { event: "agent.status.changed", event_id: 1001, session_id: "*", payload: { agent_id: "native:reviewer", status: "working", previous: "idle", reason: "agent.handoff", handoff_id: "h-build", task_id: null, at: t0 - 60 } },
    { event: "agent.handoff.checked", event_id: 1002, created_at: t0 - 30, session_id: "*", payload: { handoff: { ...build, check: { state: "pending", evidence_ref: "task:t-build", checked_by: "native:reviewer", checked_at: t0 - 30, note: "waiting on CI" } } } },
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
