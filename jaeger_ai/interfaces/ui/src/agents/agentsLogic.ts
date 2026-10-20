/* Typed port of jaeger_ai/features/webui/static/jaeger_agents_panel.js
 * (roster filtering, labels, sort order, home ids). */
import type { Agent, AgentSummary } from "../api/types";

export const INTERNAL_IDS = new Set(["native:gateway", "native:surfaces", "gateway", "surfaces"]);
const ROLE_ORDER: Record<string, number> = { lead: 0, specialist: 1, native: 2 };
/** Working roles a specialist can have (PROPOSED by the Gateway bot), with the pane's one-line description. */
export const ROLE_TEXT: Record<string, string> = {
  lead: "Lead · plans and delegates",
  "reverse-engineer": "Reverse engineer",
  builder: "Builder · code, build and test",
  reviewer: "Reviewer",
  researcher: "Researcher",
  designer: "Designer · UI",
};
const SHOWN_ROLES = new Set(["specialist", "native", ...Object.keys(ROLE_TEXT)]);

export function visible(agent: Agent): boolean {
  if (agent.hidden || agent.archived || agent.metadata?.internal) return false;
  if (INTERNAL_IDS.has(agent.id) || INTERNAL_IDS.has(agent.name)) return false;
  if (agent.kind === "third_party" || agent.id.startsWith("tp:")) return false;
  return SHOWN_ROLES.has(agent.role ?? "specialist");
}

export function label(agent: Pick<Agent, "role" | "display_name" | "name">): string {
  return agent.display_name || agent.name;
}

export function sortAgents(agents: Agent[]): Agent[] {
  return [...agents].sort((a, b) => (ROLE_ORDER[a.role ?? ""] ?? 9) - (ROLE_ORDER[b.role ?? ""] ?? 9) || label(a).localeCompare(label(b)));
}

export function homeId(agent: Pick<Agent, "name">): string {
  return `agent-${agent.name.toLowerCase().replace(/[^a-z0-9_-]+/g, "-")}`;
}

export function initials(name: string): string {
  const words = name.replace(/&/g, " ").split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : name.slice(0, 2)).toUpperCase();
}

export function runnerLabel(runner?: string | null): string | undefined {
  if (!runner || runner === "native") return undefined;
  return runner.startsWith("delegate:") ? runner.slice("delegate:".length) : runner;
}

export interface SidebarRow {
  agent: Agent;
  summary?: AgentSummary;
  lastActivityAt: number;
}

/** Lead first; specialists by latest activity, newest first (D3). */
export function sidebarRows(agents: Agent[], summaries: AgentSummary[]): { lead?: SidebarRow; specialists: SidebarRow[] } {
  const byId = new Map(summaries.map((s) => [s.id, s]));
  const rows = sortAgents(agents.filter(visible)).map((agent) => ({ agent, summary: byId.get(agent.id), lastActivityAt: byId.get(agent.id)?.last_activity_at ?? 0 }));
  return {
    lead: rows.find((r) => r.agent.primary) ?? rows.find((r) => r.agent.primary === undefined && r.agent.role === "lead"),
    specialists: rows.filter((r) => !r.agent.primary && !(r.agent.primary === undefined && r.agent.role === "lead")).sort((a, b) => b.lastActivityAt - a.lastActivityAt),
  };
}
