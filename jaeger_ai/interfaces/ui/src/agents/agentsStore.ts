import { useCallback, useEffect, useState, useRef } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent, AgentSummary, GatewayEvent } from "../api/types";
import type { Section } from "../api/agentActions";
import { loadSeen, markSeen } from "./unread";

export interface AgentsState {
  agents: Agent[];
  summaries: AgentSummary[];
  /** Server sections (GET /v1/sections), only fetched when agents carry section_id; empty otherwise. */
  sections?: Section[];
  seen: Record<string, number>;
  loading: boolean;
  /** Set when the last refresh failed. Agents keep the last REAL roster (or
   * stay empty); nothing is ever invented. */
  error?: string;
}

const POLL_MS = 15_000;

export async function loadRoster(source: Pick<JaegerSource, "agents" | "agentsSummary"> & Partial<Pick<JaegerSource, "agentActions">>) {
  const [agents, summaries] = await Promise.all([source.agents(), source.agentsSummary()]);
  if (agents.filter((a) => a.primary === true).length > 1) throw new Error("Invalid primary projection: multiple primary agents");
  const sections = source.agentActions && agents.some((a) => "section_id" in a || a.ui_actions?.sections === true) ? await source.agentActions.sections() : [];
  return { agents, summaries, sections };
}

export function useAgentsStore(source: JaegerSource) {
  const [state, setState] = useState<AgentsState>({ agents: [], summaries: [], sections: [], seen: loadSeen(), loading: true });

  const refreshVersion = useRef(0);
  const refresh = useCallback(async () => {
    const version = ++refreshVersion.current;
    setState((s) => ({ ...s, loading: true }));
    try {
      const { agents, summaries, sections } = await loadRoster(source);
      if (version === refreshVersion.current) setState((s) => ({ ...s, agents, summaries, sections, loading: false, error: undefined }));
    } catch (error) {
      if (version === refreshVersion.current) setState((s) => ({ ...s, loading: false, error: String((error as Error)?.message ?? error) }));
    }
  }, [source]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  // Live roster: agent.* / section.* refresh (debounced); agent.unread patches the agent in place. Polling above
  // stays as the fallback (and covers a gateway without the global stream).
  useEffect(() => {
    if (!source.globalEvents) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const soon = () => { ++refreshVersion.current; clearTimeout(timer); timer = setTimeout(() => void refresh(), 250); };
    void source.globalEvents((event) => onRosterEvent(event, soon, setState), abort.signal).catch(() => { /* no global stream: poll */ });
    return () => { abort.abort(); clearTimeout(timer); };
  }, [source, refresh]);

  const seeAgent = useCallback(async (agentId: string) => {
    try {
      if (source.agentActions) await source.agentActions.markRead(agentId, null);
      setState((s) => ({ ...s, seen: markSeen(agentId) }));
      if (source.agentActions) await refresh();
    } catch (error) {
      setState((s) => ({ ...s, error: `Couldn't mark this agent read: ${String((error as Error)?.message ?? error)}` }));
    }
  }, [source, refresh]);
  return { ...state, refresh, seeAgent };
}

/** Apply one global event to the roster: agent.unread in place, other agent.* / section.* via refresh. */
export function onRosterEvent(event: GatewayEvent, refresh: () => void, setState: (f: (s: AgentsState) => AgentsState) => void) {
  const name = event.event ?? "";
  if (name === "agent.unread") {
    const p = (event.payload ?? {}) as { agent_id?: string; unread_count?: number; last_message?: Agent["last_message"] };
    if (!p.agent_id) return;
    setState((s) => ({ ...s, agents: s.agents.map((a) => (a.id === p.agent_id ? { ...a, unread_count: p.unread_count ?? a.unread_count, last_message: p.last_message ?? a.last_message } : a)) }));
    return;
  }
  if (name.startsWith("agent.") || name.startsWith("section.")) refresh();
}
