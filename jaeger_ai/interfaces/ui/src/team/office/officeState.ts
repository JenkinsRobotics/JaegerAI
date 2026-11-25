/* Pixel office: who is doing what, folded from the same live records the
 * Agents › Activity panes use (agents + /v1/agents/summary statuses, handoffs,
 * tasks, agent.status.changed / agent.handoff events). No invented activity:
 * an agent with no live signal is idle. */
import type { Agent, Handoff } from "../../api/types";
import type { JaegerSource } from "../../api/source";
import { isTestOrBackup } from "../../agents/agentsLogic";
import type { AgentLive, OrchestrationSnapshot } from "../../orchestration/types";

export type Mood = "working" | "queued" | "handoff" | "approval" | "idle" | "error" | "offline";

export interface Worker {
  id: string;
  name: string;
  lead: boolean;
  seed: string;
  mood: Mood;
  /** The record behind the mood, in words (status pill + screen reader). */
  statusText: string;
  /** Short line for the speech bubble; absent when there is nothing live to say. */
  bubble?: string;
  /** Handing off: the desk this worker walks to. */
  handoffTo?: string;
  handoff?: Handoff;
  currentTask?: AgentLive["currentTask"];
  live: AgentLive;
  sessionId?: string | null;
  /** Test fixture / backup copy / hidden from the roster: off the floor by default. */
  fixture: boolean;
}

const FIXTURE = /(^|[\s:._-])(fixture|fixtures|test|tests|probe|demo|smoke|dummy|acceptance)([\s:._-]|$)|-\d{8}$/i;
export function isFixtureAgent(agent: Agent, offRoster?: boolean): boolean {
  const meta = agent.metadata ?? {};
  return Boolean(offRoster) || isTestOrBackup(agent) || FIXTURE.test(agent.id) || FIXTURE.test(agent.display_name ?? agent.name)
    || meta.fixture === true || meta.probe === true || meta.test === true;
}

/** Handoffs still on their way to the other desk (not yet picked up). */
const IN_FLIGHT = new Set(["pending_approval", "approved", "admitted"]);
const TASK_STATUS: Record<string, string> = {
  needs_owner: "waiting_approval", paused: "waiting_approval", blocked: "blocked",
  running: "working", queued: "queued",
};
const HANDOFF_STATUS: Record<string, string> = {
  pending_approval: "waiting_approval", approved: "queued", admitted: "queued", running: "working",
};
const LIVE_PRIORITY = ["waiting_approval", "blocked", "working", "queued"];
const SESSION_STATUS: Record<string, string> = { running: "working", cancelling: "blocked" };

export async function recoverMaskedChatStatus(snap: OrchestrationSnapshot, source: Pick<JaegerSource, "sessions">): Promise<OrchestrationSnapshot> {
  if (!snap.summaries.some(s => s.status === "error")) return snap;
  // Legacy summaries can rank a terminal failure above a current chat that
  // did not open a task card. Consult the gateway's scoped session metadata.
  const summaries = await Promise.all(snap.summaries.map(async s => {
    if (s.status !== "error") return s;
    const sessions = await source.sessions({ agent_id: s.id }).catch(() => []);
    const session = sessions.find(row => SESSION_STATUS[String(row.status)]);
    return session ? { ...s, status: SESSION_STATUS[String(session.status)], session_id: session.session_id } : s;
  }));
  return { ...snap, summaries };
}
/** A just-created running handoff still shows the walk for this long. */
export const HANDOFF_WALK_S = 20;

const sec = (t?: number | null) => (t ? (t > 1e12 ? t / 1000 : t) : 0);

/** "[Heartbeat checklist] This is a read-only…" -> "Heartbeat checklist"; else the first sentence, clipped. */
export function taskLine(text?: string | null, max = 64): string | undefined {
  const flat = String(text ?? "").replace(/\s+/g, " ").trim();
  if (!flat) return undefined;
  const tag = /^\[([^\]]{2,48})\]/.exec(flat);
  let line = tag ? tag[1] : flat.split(/(?<=[.!?])\s/)[0];
  line = line.replace(/^#+\s*/, "").trim();
  return line.length > max ? `${line.slice(0, max - 1).trimEnd()}…` : line;
}

const STATUS_TEXT: Record<Mood, string> = {
  working: "Working", queued: "Queued", handoff: "Handing off", approval: "Waiting on you",
  idle: "Idle", error: "Blocked", offline: "Offline",
};

export function deriveWorkers(live: AgentLive[], snap: OrchestrationSnapshot | undefined, now: number, gatewayDown: boolean): Worker[] {
  const ids = new Set(live.map((r) => r.agent.id));
  const name = (id: string) => { const a = live.find((r) => r.agent.id === id)?.agent; return a ? (a.display_name || a.name) : id.replace(/^[a-z]+:/, ""); };
  const handoffs = (snap?.handoffs ?? []).slice().sort((a, b) => sec(b.created_at ?? b.updated_at) - sec(a.created_at ?? a.updated_at));
  return live.map((row): Worker => {
    const { agent, summary } = row;
    // The gateway summary also reports historical failures. Only current work
    // from the authoritative snapshot can put a desk in a live state.
    const reported = summary?.status ?? row.status;
    const candidates = (snap?.tasks ?? []).filter(t => (t.agent_id ?? t.owning_agent) === agent.id);
    const liveTasks = candidates.filter(t => TASK_STATUS[String(t.state)]);
    if (row.currentTask && !candidates.some(t => t.task_id === row.currentTask?.task_id) && TASK_STATUS[String(row.currentTask.state)]) {
      liveTasks.push(row.currentTask);
    }
    const incoming = handoffs.find(h => h.to_agent_id === agent.id && HANDOFF_STATUS[String(h.status)]);
    const signals = new Set([reported, HANDOFF_STATUS[String(incoming?.status)], ...liveTasks.map(t => TASK_STATUS[String(t.state)])]);
    const status = LIVE_PRIORITY.find(s => signals.has(s)) ?? "idle";
    const task = liveTasks.filter(t => TASK_STATUS[String(t.state)] === status)
      .sort((a, b) => sec(b.updated_at) - sec(a.updated_at))[0];
    const out = handoffs.find((h) => h.from_agent_id === agent.id && h.to_agent_id && h.to_agent_id !== agent.id && ids.has(h.to_agent_id)
      && (IN_FLIGHT.has(String(h.status)) || (String(h.status) === "running" && now - sec(h.created_at ?? h.updated_at) < HANDOFF_WALK_S)));
    let mood: Mood;
    if (gatewayDown || agent.disabled) mood = "offline";
    else if (status === "waiting_approval") mood = "approval";
    else if (status === "blocked") mood = "error";
    else if (out) mood = "handoff";
    else if (status === "working") mood = "working";
    else if (status === "queued") mood = "queued";
    else mood = "idle";
    const goal = taskLine(task?.goal ?? (HANDOFF_STATUS[String(incoming?.status)] === status ? incoming?.task : undefined));
    const bubble = mood === "working" ? goal
      : mood === "queued" ? (goal ? `Queued · ${goal}` : "Queued")
      : mood === "approval" ? (goal ? `Needs your OK · ${goal}` : "Needs your OK")
      : mood === "handoff" && out ? `Handing to ${name(out.to_agent_id!)}`
      : mood === "error" ? (goal ? `Blocked · ${goal}` : "Work is blocked")
      : undefined;
    return {
      id: agent.id, name: agent.display_name || agent.name, lead: agent.role === "lead" || agent.id === "native:jaeger",
      seed: String(agent.metadata?.avatar_seed ?? agent.id), mood,
      statusText: STATUS_TEXT[mood],
      bubble, handoffTo: mood === "handoff" ? out?.to_agent_id : undefined,
      handoff: mood === "handoff" ? out : mood !== "offline" && HANDOFF_STATUS[String(incoming?.status)] === status ? incoming : undefined,
      currentTask: mood !== "offline" && mood !== "handoff" ? task : undefined,
      live: row, sessionId: summary?.session_id ?? null, fixture: isFixtureAgent(agent, row.offRoster),
    };
  });
}
