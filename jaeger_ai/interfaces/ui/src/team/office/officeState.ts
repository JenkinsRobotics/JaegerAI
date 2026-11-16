/* Pixel office: who is doing what, folded from the same live records the
 * Agents › Activity panes use (agents + /v1/agents/summary statuses, handoffs,
 * tasks, agent.status.changed / agent.handoff events). No invented activity:
 * an agent with no live signal is idle. Pure functions, no I/O. */
import type { Agent, Handoff } from "../../api/types";
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
  idle: "Idle", error: "Error", offline: "Offline",
};

export function deriveWorkers(live: AgentLive[], snap: OrchestrationSnapshot | undefined, now: number, gatewayDown: boolean): Worker[] {
  const ids = new Set(live.map((r) => r.agent.id));
  const name = (id: string) => { const a = live.find((r) => r.agent.id === id)?.agent; return a ? (a.display_name || a.name) : id.replace(/^[a-z]+:/, ""); };
  const handoffs = (snap?.handoffs ?? []).slice().sort((a, b) => sec(b.created_at ?? b.updated_at) - sec(a.created_at ?? a.updated_at));
  return live.map((row): Worker => {
    const { agent, summary } = row;
    const status = String(row.status || "idle");
    const out = handoffs.find((h) => h.from_agent_id === agent.id && h.to_agent_id && h.to_agent_id !== agent.id && ids.has(h.to_agent_id)
      && (IN_FLIGHT.has(String(h.status)) || (String(h.status) === "running" && now - sec(h.created_at ?? h.updated_at) < HANDOFF_WALK_S)));
    let mood: Mood;
    if (gatewayDown || agent.disabled) mood = "offline";
    else if (status === "error") mood = "error";
    else if (status === "waiting_approval" || status === "blocked") mood = "approval";
    else if (out) mood = "handoff";
    else if (status === "working") mood = "working";
    else if (status === "queued") mood = "queued";
    else mood = "idle";
    const goal = taskLine(row.currentTask?.goal) ?? taskLine(summary?.last_preview);
    const bubble = mood === "working" ? goal
      : mood === "queued" ? (goal ? `Queued · ${goal}` : "Queued")
      : mood === "approval" ? (status === "blocked" ? "Blocked" : "Needs your OK") + (goal ? ` · ${goal}` : "")
      : mood === "handoff" && out ? `Handing to ${name(out.to_agent_id!)}`
      : mood === "error" ? (goal ? `Failed · ${goal}` : "Something failed")
      : undefined;
    return {
      id: agent.id, name: agent.display_name || agent.name, lead: agent.role === "lead" || agent.id === "native:jaeger",
      seed: String(agent.metadata?.avatar_seed ?? agent.id), mood,
      statusText: mood === "approval" && status === "blocked" ? "Blocked" : STATUS_TEXT[mood],
      bubble, handoffTo: mood === "handoff" ? out?.to_agent_id : undefined, handoff: mood === "handoff" ? out : undefined,
      live: row, sessionId: summary?.session_id ?? null, fixture: isFixtureAgent(agent, row.offRoster),
    };
  });
}
